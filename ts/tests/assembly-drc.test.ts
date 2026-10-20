/**
 * CW-A04 (CW-DRC-01..03) test suite: pure DRC solver, routing proposals,
 * power rail conversion/derating/brownout, 3D rotated/parallel-axis inertia,
 * unknown-aware BOM, and epoch-fenced worker rejection.
 * Synthetic fixtures below are explicitly labeled and never qualify physical hardware.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import {
  canonicalAssemblyString,
  parseAssemblyText,
  type RobotAssembly,
} from '../packages/contracts/src/index.js';
import {
  DrcWorkerCoordinator,
  ESP32_S3_RESERVED_PINS,
  evaluateAssemblyDrc,
  handleDrcWorkerMessage,
  isValidInertiaTensor,
  parseDrcCatalogFromRaw,
  rotateInertiaTensor,
  sha256Hex,
  verifyInertiaAggregationFidelity,
  type DrcCatalog,
  type DrcPart,
} from '../packages/drc-solver/src/index.js';

const starterRaw = readFileSync(
  new URL('../../packages/component-registry/assemblies/tabletop-starter.sc-assembly.json', import.meta.url),
  'utf8',
);
const starterAssembly = parseAssemblyText(starterRaw);

function loadRealDrcCatalog(): DrcCatalog {
  const catalogRawJson = readFileSync(
    new URL('../../packages/component-registry/catalog.json', import.meta.url),
    'utf8',
  );
  const catalogSha256 = createHash('sha256').update(catalogRawJson).digest('hex');
  const index = JSON.parse(catalogRawJson) as { parts: { part_id: string; path: string }[] };
  const partDocuments = index.parts.map(entry => ({
    part_id: entry.part_id,
    raw_json: readFileSync(
      new URL(`../../packages/component-registry/${entry.path}`, import.meta.url),
      'utf8',
    ),
  }));
  return parseDrcCatalogFromRaw({
    catalogSha256,
    catalogRawJson,
    partDocuments,
    provenance: 'verified_local_catalog',
  });
}

function makeSyntheticQualifiedFixture(): { assembly: RobotAssembly; catalog: DrcCatalog } {
  const realCatalog = loadRealDrcCatalog();
  const assembly = structuredClone(starterAssembly);

  const syntheticParts: DrcPart[] = realCatalog.parts.map(p => {
    const clone = structuredClone(p);
    clone.status = 'documented';
    clone.costBasis = 'supplier_quote';
    clone.bomCostUsd =
      p.partId === 'espressif.esp32-s3-draft'
        ? 12.0
        : p.partId === 'feetech.sts3215-draft'
          ? 18.5
          : p.partId === 'generic.bec-draft'
            ? 6.5
            : p.partId === 'generic.lipo2s-draft'
              ? 14.0
              : 4.0;
    clone.supplierSkus = [
      {
        supplier: 'SyntheticFixtureSupplier',
        sku: `SYN-${p.partId.toUpperCase()}`,
        url: 'https://example.com/synthetic-fixture',
        quoted_on: '2026-10-19',
      },
    ];
    clone.mechanical.basis = 'drawing_reviewed';
    clone.mechanical.snapPorts = clone.mechanical.snapPorts.map(port => ({
      ...port,
      qualification: 'drawing_reviewed',
    }));
    if (p.category === 'chassis') {
      clone.electrical.ratingBasis = 'not_applicable';
    } else if (p.partId === 'espressif.esp32-s3-draft') {
      clone.electrical = {
        ratingBasis: 'documented',
        minV: 3.0,
        maxV: 3.6,
        continuousMa: 120,
        peakMa: 350,
        outputCapacityMa: null,
        busInterfaces: [
          {
            interface_id: 'uart',
            kind: 'TTL_UART_BUS',
            role: 'controller',
            protocol: 'feetech_sts_ttl',
            logic_min_v: 3.0,
            logic_max_v: 3.6,
            i2c_address: null,
            pins: ['GPIO17', 'GPIO18'],
          },
          {
            interface_id: 'i2c',
            kind: 'I2C',
            role: 'controller',
            protocol: 'smbus_i2c_v1',
            logic_min_v: 3.0,
            logic_max_v: 3.6,
            i2c_address: null,
            pins: ['GPIO8', 'GPIO9'],
          },
          {
            interface_id: 'power_in',
            kind: 'POWER_RAIL',
            role: 'sink',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['3V3', 'GND'],
          },
        ],
      };
    } else if (p.partId === 'feetech.sts3215-draft') {
      clone.electrical = {
        ratingBasis: 'documented',
        minV: 5.0,
        maxV: 7.4,
        continuousMa: 300,
        peakMa: 1200,
        outputCapacityMa: null,
        busInterfaces: [
          {
            interface_id: 'servo-bus',
            kind: 'TTL_UART_BUS',
            role: 'peripheral',
            protocol: 'feetech_sts_ttl',
            logic_min_v: 3.0,
            logic_max_v: 5.0,
            i2c_address: null,
            pins: ['DATA'],
          },
          {
            interface_id: 'power_in',
            kind: 'POWER_RAIL',
            role: 'sink',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['VIN', 'GND'],
          },
        ],
      };
    } else if (p.partId === 'generic.mpu6050-draft') {
      clone.electrical = {
        ratingBasis: 'documented',
        minV: 3.0,
        maxV: 3.6,
        continuousMa: 5,
        peakMa: 10,
        outputCapacityMa: null,
        busInterfaces: [
          {
            interface_id: 'control',
            kind: 'I2C',
            role: 'peripheral',
            protocol: 'smbus_i2c_v1',
            logic_min_v: 3.0,
            logic_max_v: 3.6,
            i2c_address: 0x68,
            pins: ['SDA', 'SCL'],
          },
          {
            interface_id: 'power_in',
            kind: 'POWER_RAIL',
            role: 'sink',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['VCC', 'GND'],
          },
        ],
      };
    } else if (p.partId === 'generic.bec-draft') {
      clone.electrical = {
        ratingBasis: 'documented',
        minV: 6.5,
        maxV: 8.4,
        continuousMa: 0,
        peakMa: 0,
        outputCapacityMa: 3000,
        busInterfaces: [
          {
            interface_id: 'input',
            kind: 'POWER_RAIL',
            role: 'sink',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['VIN_POS', 'VIN_NEG'],
          },
          {
            interface_id: 'output',
            kind: 'POWER_RAIL',
            role: 'source',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['VOUT_POS', 'VOUT_NEG'],
          },
        ],
      };
    } else if (p.partId === 'generic.lipo2s-draft') {
      clone.electrical = {
        ratingBasis: 'documented',
        minV: 6.8,
        maxV: 8.4,
        continuousMa: 0,
        peakMa: 0,
        outputCapacityMa: 5000,
        busInterfaces: [
          {
            interface_id: 'output',
            kind: 'POWER_RAIL',
            role: 'source',
            protocol: null,
            logic_min_v: null,
            logic_max_v: null,
            i2c_address: null,
            pins: ['VBAT_POS', 'VBAT_NEG'],
          },
        ],
      };
    }
    return clone;
  });

  // Add BEC and battery to the synthetic assembly to power servo_0 and mcu_0
  const becPart = syntheticParts.find(p => p.partId === 'generic.bec-draft')!;
  const batPart = syntheticParts.find(p => p.partId === 'generic.lipo2s-draft')!;
  assembly.nodes.push(
    {
      node_id: 'bec_0',
      part_id: becPart.partId,
      part_version: becPart.version,
      part_sha256: becPart.sha256,
      role: 'power',
    },
    {
      node_id: 'bat_0',
      part_id: batPart.partId,
      part_version: batPart.version,
      part_sha256: batPart.sha256,
      role: 'power',
    },
  );
  assembly.mechanical_tree.push(
    {
      edge_id: 'edge_mcu_bec',
      parent_node_id: 'mcu_0',
      parent_port_id: 'mount.top',
      child_node_id: 'bec_0',
      child_port_id: 'mount.bottom',
      connection_type: 'rigid_mount',
      relative_transform: { position_m: [0, 0, 0.009], quaternion_wxyz: [1, 0, 0, 0] },
    },
    {
      edge_id: 'edge_bec_bat',
      parent_node_id: 'bec_0',
      parent_port_id: 'mount.top',
      child_node_id: 'bat_0',
      child_port_id: 'mount.bottom',
      relative_transform: { position_m: [0, 0, 0.014], quaternion_wxyz: [1, 0, 0, 0] },
      connection_type: 'rigid_mount',
    },
  );
  assembly.electrical_nets = [
    {
      net_id: 'net_servo_ttl',
      kind: 'TTL_UART_BUS',
      nominal_voltage_v: 3.3,
      endpoints: [
        { node_id: 'mcu_0', interface_id: 'uart', pins: ['GPIO17', 'GPIO18'] },
        { node_id: 'servo_0', interface_id: 'servo-bus', pins: ['DATA'] },
      ],
    },
    {
      net_id: 'rail_servo_6v',
      kind: 'power',
      nominal_voltage_v: 6.0,
      endpoints: [
        { node_id: 'bec_0', interface_id: 'output', pins: ['VOUT_POS'] },
        { node_id: 'servo_0', interface_id: 'power_in', pins: ['VIN'] },
      ],
    },
    {
      net_id: 'rail_mcu_3v3',
      kind: 'power',
      nominal_voltage_v: 3.3,
      endpoints: [
        { node_id: 'bat_0', interface_id: 'output', pins: ['VBAT_POS'] },
        { node_id: 'mcu_0', interface_id: 'power_in', pins: ['3V3'] },
      ],
    },
    {
      net_id: 'rail_vbat_7v4',
      kind: 'power',
      nominal_voltage_v: 7.4,
      endpoints: [
        { node_id: 'bat_0', interface_id: 'output', pins: ['VBAT_POS'] },
        { node_id: 'bec_0', interface_id: 'input', pins: ['VIN_POS'] },
      ],
    },
  ];
  // Adjust bat_0 min/max to allow 3.3V on the synthetic fixture or give mcu_0 a 7.4V Vin regulator input
  const mcu = syntheticParts.find(p => p.partId === 'espressif.esp32-s3-draft')!;
  mcu.electrical.minV = 3.0;
  mcu.electrical.maxV = 3.6;

  return {
    assembly,
    catalog: {
      catalogDigest: 'f'.repeat(64),
      provenance: 'synthetic_fixture',
      parts: syntheticParts,
    },
  };
}

test('synchronous sha256Hex matches Node crypto SHA-256 across empty, ASCII, and UTF-8 inputs', () => {
  for (const sample of ['', 'seedcore.assembly.v2', starterRaw, '{"unicode":"🤖"}']) {
    const expected = createHash('sha256').update(sample, 'utf8').digest('hex');
    assert.equal(sha256Hex(sample), expected);
  }
});

test('reviewed tabletop starter produces deterministic blocked findings, exact digests, mass/COM, and unknown-aware BOM', () => {
  const catalog = loadRealDrcCatalog();
  const report = evaluateAssemblyDrc(starterAssembly, catalog);

  assert.equal(report.schemaVersion, 'seedcore.drc.report.v1');
  assert.equal(report.scope, 'offline_proxy_authoring');
  assert.equal(report.physicalAcceptance, false);
  assert.equal(report.executionAuthority, 'none');
  assert.equal(report.catalogProvenance, 'verified_local_catalog');
  assert.equal(
    report.assemblyDigest,
    '2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb',
  );
  assert.match(report.electricalPlanDigest, /^[a-f0-9]{64}$/);
  assert.equal(report.disposition, 'blocked');
  assert.equal(report.counts.conflict, 0);
  assert.ok(report.counts.blocked >= 5);

  // Servo ID assignment on net_servo_ttl
  assert.deepEqual(report.servoAddressesByNet, { net_servo_ttl: { servo_0: 1 } });
  assert.equal(report.routingProposals.length, 1);
  assert.equal(report.routingProposals[0].netId, 'net_servo_ttl');
  assert.equal(report.routingProposals[0].status, 'blocked');

  // Mass & COM checks
  assert.ok(Math.abs(report.massProperties.totalMassKg - 0.22) < 1e-12);
  assert.ok(Math.abs(report.massProperties.centerOfMassWorldM[0]) < 1e-12);
  assert.ok(Math.abs(report.massProperties.centerOfMassWorldM[1]) < 1e-12);
  assert.ok(
    Math.abs(report.massProperties.centerOfMassWorldM[2] - 0.004975 / 0.22) < 1e-12,
  );
  assert.equal(report.massProperties.allPartsDrawingReviewed, false);
  assert.equal(isValidInertiaTensor(report.massProperties.inertiaWorldAtComKgM2).valid, true);

  // Unknown-Aware BOM checks: unknown prices are excluded, never treated as $0 free
  assert.equal(report.bom.knownSubtotalUsd, 0);
  assert.equal(report.bom.pricedPartCount, 0);
  assert.equal(report.bom.unpricedPartCount, 5);
  assert.equal(report.bom.uniquePartCount, 5);
  assert.equal(report.bom.completePricing, false);
  assert.ok(report.bom.lines.every(line => line.unitCostUsd === null && line.lineTotalUsd === null));

  const codes = new Set(report.findings.map(f => f.code));
  for (const requiredCode of [
    'GPIO_PINS_UNASSIGNED',
    'UART_PROTOCOL_UNKNOWN',
    'UART_LOGIC_VOLTAGE_UNKNOWN',
    'POWER_UNKNOWN_RATING',
    'POWER_RAIL_UNCONNECTED',
    'MECHANICAL_PROXY_UNQUALIFIED',
    'BOM_UNPRICED_PARTS',
  ]) {
    assert.ok(codes.has(requiredCode), `Missing expected starter finding code: ${requiredCode}`);
  }
});

test('synthetic fully documented and compatible fixture achieves pass disposition without granting authority', () => {
  const { assembly, catalog } = makeSyntheticQualifiedFixture();
  const report = evaluateAssemblyDrc(assembly, catalog);

  assert.equal(report.catalogProvenance, 'synthetic_fixture');
  assert.equal(report.disposition, 'pass');
  assert.deepEqual(report.counts, { conflict: 0, blocked: 0 });
  assert.equal(report.physicalAcceptance, false);
  assert.equal(report.executionAuthority, 'none');
  assert.equal(report.bom.completePricing, true);
  assert.equal(report.bom.unpricedPartCount, 0);
  assert.equal(report.bom.pricedPartCount, 7);
  assert.ok(report.bom.knownSubtotalUsd > 0);
});

test('CW-DRC-01: mixed protocols, duplicate/unsupported servo IDs, and disjoint logic voltages produce conflicts', () => {
  const { assembly, catalog } = makeSyntheticQualifiedFixture();
  const servoPart = catalog.parts.find(p => p.partId === 'feetech.sts3215-draft')!;
  servoPart.electrical.busInterfaces[0].protocol = 'dynamixel_ttl_v2';

  const mixedReport = evaluateAssemblyDrc(assembly, catalog);
  assert.equal(mixedReport.disposition, 'conflict');
  assert.ok(mixedReport.findings.some(f => f.code === 'UART_PROTOCOL_MISMATCH'));

  // Restore protocol and test out-of-range servo ID
  servoPart.electrical.busInterfaces[0].protocol = 'feetech_sts_ttl';
  const badIdReport = evaluateAssemblyDrc(assembly, catalog, { servoIds: { servo_0: 254 } });
  assert.equal(badIdReport.disposition, 'conflict');
  assert.ok(badIdReport.findings.some(f => f.code === 'UART_ID_OUT_OF_RANGE'));

  // Test duplicate servo IDs when two servos share the bus
  const twoServo = structuredClone(assembly);
  twoServo.nodes.push({
    node_id: 'servo_1',
    part_id: servoPart.partId,
    part_version: servoPart.version,
    part_sha256: servoPart.sha256,
    role: 'actuator',
  });
  twoServo.mechanical_tree.push({
    edge_id: 'edge_bat_servo1',
    parent_node_id: 'bat_0',
    parent_port_id: 'mount.top',
    child_node_id: 'servo_1',
    child_port_id: 'mount.bottom',
    connection_type: 'rigid_mount',
    relative_transform: { position_m: [0, 0, 0.029], quaternion_wxyz: [1, 0, 0, 0] },
  });
  twoServo.electrical_nets[0].endpoints.push({
    node_id: 'servo_1',
    interface_id: 'servo-bus',
    pins: ['DATA'],
  });
  twoServo.electrical_nets[1].endpoints.push({
    node_id: 'servo_1',
    interface_id: 'power_in',
    pins: ['VIN'],
  });
  const dupIdReport = evaluateAssemblyDrc(twoServo, catalog, {
    servoIds: { servo_0: 7, servo_1: 7 },
  });
  assert.equal(dupIdReport.disposition, 'conflict');
  assert.ok(dupIdReport.findings.some(f => f.code === 'UART_DUPLICATE_SERVO_ID'));

  // Auto-assigned IDs are deterministic and unique across node array reorderings
  const autoA = evaluateAssemblyDrc(twoServo, catalog);
  const reversed = structuredClone(twoServo);
  reversed.nodes.reverse();
  const autoB = evaluateAssemblyDrc(reversed, catalog);
  assert.deepEqual(autoA.servoAddressesByNet, {
    net_servo_ttl: { servo_0: 1, servo_1: 2 },
  });
  assert.deepEqual(autoA.servoAddressesByNet, autoB.servoAddressesByNet);
});

test('CW-DRC-01: reserved ESP32-S3 boot/USB/flash/PSRAM pins and pin reuse conflicts are rejected', () => {
  for (const reservedPin of ['GPIO0', 'GPIO19', 'GPIO20', 'GPIO35']) {
    assert.ok(ESP32_S3_RESERVED_PINS.has(reservedPin));
    const { assembly, catalog } = makeSyntheticQualifiedFixture();
    assembly.electrical_nets[0].endpoints[0].pins = [reservedPin, 'GPIO18'];
    const report = evaluateAssemblyDrc(assembly, catalog);
    assert.equal(report.disposition, 'conflict');
    assert.ok(
      report.findings.some(
        f => f.code === 'GPIO_RESERVED_PIN' && f.fieldRefs.includes('/electrical_nets/0/endpoints/0'),
      ),
    );
  }

  // Pin conflict when I2C and UART share GPIO18 on mcu_0
  const { assembly, catalog } = makeSyntheticQualifiedFixture();
  const imuPart = catalog.parts.find(p => p.partId === 'generic.mpu6050-draft')!;
  assembly.nodes.push({
    node_id: 'imu_0',
    part_id: imuPart.partId,
    part_version: imuPart.version,
    part_sha256: imuPart.sha256,
    role: 'sensor',
  });
  assembly.mechanical_tree.push({
    edge_id: 'edge_bat_imu',
    parent_node_id: 'bat_0',
    parent_port_id: 'mount.top',
    child_node_id: 'imu_0',
    child_port_id: 'mount.bottom',
    connection_type: 'rigid_mount',
    relative_transform: { position_m: [0, 0, 0.011], quaternion_wxyz: [1, 0, 0, 0] },
  });
  assembly.electrical_nets.push(
    {
      net_id: 'net_i2c',
      kind: 'I2C',
      nominal_voltage_v: 3.3,
      endpoints: [
        { node_id: 'mcu_0', interface_id: 'i2c', pins: ['GPIO18', 'GPIO9'] },
        { node_id: 'imu_0', interface_id: 'control', pins: ['SDA', 'SCL'] },
      ],
    },
    {
      net_id: 'rail_imu',
      kind: 'power',
      nominal_voltage_v: 3.3,
      endpoints: [
        { node_id: 'bat_0', interface_id: 'output', pins: ['VBAT_POS'] },
        { node_id: 'imu_0', interface_id: 'power_in', pins: ['VCC'] },
      ],
    },
  );
  const pinConflict = evaluateAssemblyDrc(assembly, catalog);
  assert.equal(pinConflict.disposition, 'conflict');
  assert.ok(pinConflict.findings.some(f => f.code === 'GPIO_PIN_CONFLICT'));
});

test('CW-DRC-01: I2C duplicate address collision without mux and incompatible pull-up voltage are rejected', () => {
  const { assembly, catalog } = makeSyntheticQualifiedFixture();
  const imuPart = catalog.parts.find(p => p.partId === 'generic.mpu6050-draft')!;
  assembly.nodes.push(
    {
      node_id: 'imu_0',
      part_id: imuPart.partId,
      part_version: imuPart.version,
      part_sha256: imuPart.sha256,
      role: 'sensor',
    },
    {
      node_id: 'imu_1',
      part_id: imuPart.partId,
      part_version: imuPart.version,
      part_sha256: imuPart.sha256,
      role: 'sensor',
    },
  );
  assembly.mechanical_tree.push(
    {
      edge_id: 'edge_bat_imu0',
      parent_node_id: 'bat_0',
      parent_port_id: 'mount.top',
      child_node_id: 'imu_0',
      child_port_id: 'mount.bottom',
      connection_type: 'rigid_mount',
      relative_transform: { position_m: [0, 0, 0.011], quaternion_wxyz: [1, 0, 0, 0] },
    },
    {
      edge_id: 'edge_imu0_imu1',
      parent_node_id: 'imu_0',
      parent_port_id: 'mount.top',
      child_node_id: 'imu_1',
      child_port_id: 'mount.bottom',
      connection_type: 'rigid_mount',
      relative_transform: { position_m: [0, 0, 0.004], quaternion_wxyz: [1, 0, 0, 0] },
    },
  );
  assembly.electrical_nets.push({
    net_id: 'net_i2c_bus',
    kind: 'I2C',
    nominal_voltage_v: 3.3,
    endpoints: [
      { node_id: 'mcu_0', interface_id: 'i2c', pins: ['GPIO8', 'GPIO9'] },
      { node_id: 'imu_0', interface_id: 'control', pins: ['SDA', 'SCL'] },
      { node_id: 'imu_1', interface_id: 'control', pins: ['SDA', 'SCL'] },
    ],
  });
  assembly.electrical_nets[2].endpoints.push(
    { node_id: 'imu_0', interface_id: 'power_in', pins: ['VCC'] },
    { node_id: 'imu_1', interface_id: 'power_in', pins: ['VCC'] },
  );

  const collision = evaluateAssemblyDrc(assembly, catalog);
  assert.equal(collision.disposition, 'conflict');
  assert.ok(collision.findings.some(f => f.code === 'I2C_ADDRESS_COLLISION'));

  // With reviewed I2C mux enabled, address collision is resolved; pull-up voltage mismatch still fails
  const badPullUp = evaluateAssemblyDrc(assembly, catalog, {
    i2cMuxByNet: { net_i2c_bus: true },
    i2cPullUpVoltageByNet: { net_i2c_bus: 5.0 },
  });
  assert.equal(badPullUp.disposition, 'conflict');
  assert.ok(!badPullUp.findings.some(f => f.code === 'I2C_ADDRESS_COLLISION'));
  assert.ok(badPullUp.findings.some(f => f.code === 'I2C_PULLUP_MISMATCH'));
});

test('CW-DRC-02: brownout margin, BEC/wire/fuse overload, distribution board rule, MCU single-count, and unlike-voltage power conversion', () => {
  const { assembly, catalog } = makeSyntheticQualifiedFixture();

  // 1. Missing brownout margin on rail_servo_6v when line drop is 0.85 V (6.0 - 0.85 = 5.15 V -> 0.15 V margin < 0.3 V required)
  const brownout = evaluateAssemblyDrc(assembly, catalog, {
    lineDropVByNet: { rail_servo_6v: 0.85 },
    brownoutMarginV: 0.3,
  });
  assert.equal(brownout.disposition, 'conflict');
  assert.ok(brownout.findings.some(f => f.code === 'POWER_BROWNOUT_MARGIN'));

  // 2. Overloaded BEC after 0.8 derating (servo peak = 1200 mA; set BEC outputCapacityMa = 1400 mA -> derated 1120 mA < 1200 mA)
  const bec = catalog.parts.find(p => p.partId === 'generic.bec-draft')!;
  bec.electrical.outputCapacityMa = 1400;
  const becOverload = evaluateAssemblyDrc(assembly, catalog, {
    distributionNodeIds: ['hat_0'],
  });
  assert.equal(becOverload.disposition, 'conflict');
  const becFinding = becOverload.findings.find(f => f.code === 'POWER_OVERLOAD_BEC');
  assert.ok(becFinding);
  assert.match(becFinding.recommendation ?? '', /distribution board/i);
  bec.electrical.outputCapacityMa = 3000;

  // 3. Overloaded wire and fuse ratings
  const wireOverload = evaluateAssemblyDrc(assembly, catalog, {
    wireLimitMaByNet: { rail_servo_6v: 1000 },
    fuseLimitMaByNet: { rail_servo_6v: 1100 },
  });
  assert.equal(wireOverload.disposition, 'conflict');
  assert.equal(
    wireOverload.findings.filter(f => f.code === 'POWER_OVERLOAD_WIRE_FUSE').length,
    2,
  );

  // 4. Distribution board alone is not a power source
  const distOnly = evaluateAssemblyDrc(assembly, catalog, {
    distributionNodeIds: ['bec_0'],
  });
  assert.equal(distOnly.disposition, 'conflict');
  assert.ok(distOnly.findings.some(f => f.code === 'POWER_DISTRIBUTION_NOT_SOURCE'));

  // 5. MCU connected to multiple signal nets + duplicate endpoint is counted once on its supply rail
  const baseReport = evaluateAssemblyDrc(assembly, catalog);
  const mcuRail = baseReport.powerRails.find(r => r.netId === 'rail_mcu_3v3')!;
  assert.equal(mcuRail.continuousLoadMa, 120);
  assert.equal(mcuRail.peakLoadMa, 350);

  // Downstream 6.0V * 1.2A = 7.2W / 0.85 efficiency = 8.4706W reflected onto 7.4V battery rail (minV 6.5V -> ~1303.17 mA)
  const vbatRail = baseReport.powerRails.find(r => r.netId === 'rail_vbat_7v4')!;
  assert.ok(vbatRail.reflectedUpstreamPeakMa !== null && vbatRail.reflectedUpstreamPeakMa > 1300);

  // Explicit assertions for double-counted MCU or summed currents across unlike voltages
  const badPowerMath = evaluateAssemblyDrc(assembly, catalog, {
    claimedLoadAssertions: { mcuCountedTimes: 2, summedUnlikeVoltageCurrents: true },
  });
  assert.equal(badPowerMath.disposition, 'conflict');
  assert.ok(badPowerMath.findings.some(f => f.code === 'POWER_MCU_DOUBLE_COUNTED'));
  assert.ok(badPowerMath.findings.some(f => f.code === 'POWER_SUMMED_UNLIKE_VOLTAGES'));
});

test('CW-DRC-03: 3D rotated/translated inertia preserves off-diagonal terms, rejects invalid tensors, and enforces unknown-aware BOM', () => {
  const { assembly, catalog } = makeSyntheticQualifiedFixture();

  // Rotate servo_0 -> hat_0 joint and offset COM to verify off-diagonal terms & parallel-axis theorem
  const rotatedAssembly = structuredClone(assembly);
  const s = Math.SQRT1_2;
  rotatedAssembly.mechanical_tree[0].relative_transform = {
    position_m: [0.03, 0.04, 0.011],
    quaternion_wxyz: [0.5, 0.5, 0.5, 0.5],
  };
  const fidelity = verifyInertiaAggregationFidelity(rotatedAssembly, catalog);
  assert.ok(
    fidelity.offDiagonalMagnitude > 1e-6,
    `Expected nonzero off-diagonal inertia terms on 3D rotated/offset assembly, got ${fidelity.offDiagonalMagnitude}`,
  );
  assert.ok(
    fidelity.parallelAxisShiftMagnitude > 1e-5,
    `Expected significant parallel-axis shift, got ${fidelity.parallelAxisShiftMagnitude}`,
  );

  // Rotating a part inertia tensor preserves its principal moments (eigenvalues)
  const sampleTensor = { ixx: 2e-5, iyy: 4e-5, izz: 5e-5, ixy: 0, ixz: 0, iyz: 0 };
  const rotatedTensor = rotateInertiaTensor(sampleTensor, [s, s, 0, 0]);
  const origMoments = isValidInertiaTensor(sampleTensor).principalMoments;
  const rotMoments = isValidInertiaTensor(rotatedTensor).principalMoments;
  origMoments.forEach((m, idx) => assert.ok(Math.abs(m - rotMoments[idx]) < 1e-12));

  // Invalid inertia tensor violating triangle inequality (izz > ixx + iyy)
  const badInertiaCatalog = structuredClone(catalog);
  badInertiaCatalog.parts[0].mechanical.inertiaKgM2 = {
    ixx: 1e-5,
    iyy: 1e-5,
    izz: 5e-5,
    ixy: 0,
    ixz: 0,
    iyz: 0,
  };
  const badInertiaReport = evaluateAssemblyDrc(assembly, badInertiaCatalog);
  assert.equal(badInertiaReport.disposition, 'conflict');
  assert.ok(badInertiaReport.findings.some(f => f.code === 'MASS_INERTIA_INVALID'));

  // Wrong COM origin/units (e.g., millimeter value 15.0 entered in meter field)
  const badComCatalog = structuredClone(catalog);
  badComCatalog.parts[0].mechanical.centerOfMassM = [15.0, 0, 0];
  const badComReport = evaluateAssemblyDrc(assembly, badComCatalog);
  assert.equal(badComReport.disposition, 'conflict');
  assert.ok(badComReport.findings.some(f => f.code === 'MASS_COM_ORIGIN_OR_UNITS_INVALID'));

  // Unknown price treated as $0 free is rejected as a conflict
  const freePriceCatalog = structuredClone(catalog);
  freePriceCatalog.parts[0].costBasis = 'unknown';
  freePriceCatalog.parts[0].bomCostUsd = 0;
  const freePriceReport = evaluateAssemblyDrc(assembly, freePriceCatalog);
  assert.equal(freePriceReport.disposition, 'conflict');
  assert.ok(freePriceReport.findings.some(f => f.code === 'BOM_COST_BASIS_CONFLICT'));

  const zeroEstimateCatalog = structuredClone(catalog);
  zeroEstimateCatalog.parts[0].costBasis = 'estimate';
  zeroEstimateCatalog.parts[0].bomCostUsd = 0;
  const zeroEstReport = evaluateAssemblyDrc(assembly, zeroEstimateCatalog);
  assert.equal(zeroEstReport.disposition, 'conflict');
  assert.ok(zeroEstReport.findings.some(f => f.code === 'BOM_ZERO_OR_NEGATIVE_PRICE'));
});

test('CW-A04 worker coordinator fences slow stale responses and ABA authority-epoch changes', async () => {
  const catalog = loadRealDrcCatalog();
  let liveRef = {
    revisionDigest: '1'.repeat(64),
    assemblyDigest: sha256Hex(canonicalAssemblyString(starterAssembly)),
    catalogDigest: catalog.catalogDigest,
    authorityEpoch: 1,
  };

  let releaseFirst!: () => void;
  const firstGate = new Promise<void>(resolve => {
    releaseFirst = resolve;
  });
  let callCount = 0;

  const coordinator = new DrcWorkerCoordinator(
    () => liveRef,
    async req => {
      callCount++;
      if (callCount === 1) {
        await firstGate;
      }
      return handleDrcWorkerMessage(req);
    },
  );

  // Start first slow worker evaluation
  const firstPromise = coordinator.evaluate({
    revisionDigest: liveRef.revisionDigest,
    authorityEpoch: liveRef.authorityEpoch,
    assembly: starterAssembly,
    catalog,
  });

  // Simulate a newer edit arriving before the first worker completes
  const editedAssembly = structuredClone(starterAssembly);
  editedAssembly.identity.name = 'Newer Revision Wins DRC';
  liveRef = {
    revisionDigest: '2'.repeat(64),
    assemblyDigest: sha256Hex(canonicalAssemblyString(editedAssembly)),
    catalogDigest: catalog.catalogDigest,
    authorityEpoch: 2,
  };

  const secondOutcome = await coordinator.evaluate({
    revisionDigest: liveRef.revisionDigest,
    authorityEpoch: liveRef.authorityEpoch,
    assembly: editedAssembly,
    catalog,
  });
  assert.equal(secondOutcome.status, 'committed');

  // Now release the first slow worker; it must be fenced as 'stale' and never overwrite latestCommitted
  releaseFirst();
  const firstOutcome = await firstPromise;
  assert.equal(firstOutcome.status, 'stale');
  assert.equal(coordinator.getLatest()?.revisionDigest, '2'.repeat(64));
  assert.equal(coordinator.getLatest()?.authorityEpoch, 2);

  // ABA epoch test: undo returns to revisionDigest '1'.repeat(64), but authorityEpoch is now 3
  liveRef = {
    revisionDigest: '1'.repeat(64),
    assemblyDigest: sha256Hex(canonicalAssemblyString(starterAssembly)),
    catalogDigest: catalog.catalogDigest,
    authorityEpoch: 3,
  };
  const staleEpochOutcome = await coordinator.evaluate({
    revisionDigest: '1'.repeat(64),
    authorityEpoch: 1, // old epoch
    assembly: starterAssembly,
    catalog,
  });
  assert.equal(staleEpochOutcome.status, 'stale');
  assert.equal(coordinator.getLatest()?.authorityEpoch, 2);
});
