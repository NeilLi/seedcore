"use strict";
// One source for the classic browser/worker runtime and TypeScript bindings.
var MiniSimContracts;
(function (MiniSimContracts) {
    MiniSimContracts.PROTOCOL = 'seedcore.mini-lab.worker.v2';
    MiniSimContracts.MODEL_SCHEMA = 'seedcore.mini-lab.planar-model.v1';
    MiniSimContracts.ENGINE = '0.1.0-planar-arm';
    MiniSimContracts.DT = 1 / 480, MiniSimContracts.TOTAL_TICKS = 2880, MiniSimContracts.CHUNK_TICKS = 8;
    MiniSimContracts.POOL_SIZE = 3, MiniSimContracts.BUFFER_BYTES = 2 * 6 * 8, MiniSimContracts.MAX_INPUTS = 32;
    function validCheckpoint(value, identity, buildDigest) {
        if (!object(value) || !keys(value, ['schema', 'engine', 'buildDigest', 'modelDigest', 'recipeDigest', 'tick', 'state', 'control', 'started', 'inputs']) ||
            value.schema !== 'seedcore.mini-lab.checkpoint.v1' || value.engine !== MiniSimContracts.ENGINE || value.buildDigest !== buildDigest ||
            value.modelDigest !== identity.modelDigest || value.recipeDigest !== identity.recipeDigest ||
            !Number.isSafeInteger(value.tick) || !bounded(value.tick, 0, MiniSimContracts.TOTAL_TICKS) || value.tick % MiniSimContracts.CHUNK_TICKS !== 0 ||
            !object(value.state) || !keys(value.state, ['q', 'velocity', 'time']) || !validState(value.state, value.tick) || !validControl(value.control) || typeof value.started !== 'boolean' ||
            (value.tick > 0 && !value.started) || !Array.isArray(value.inputs) || value.inputs.length > MiniSimContracts.MAX_INPUTS)
            return false;
        let previousTick = -1, previousSequence = 0;
        const sequences = new Set();
        for (const input of value.inputs) {
            if (!object(input) || !keys(input, ['sequence', 'applicationTick', 'control']) ||
                !Number.isSafeInteger(input.sequence) || !bounded(input.sequence, 1, Number.MAX_SAFE_INTEGER) || sequences.has(input.sequence) ||
                !Number.isSafeInteger(input.applicationTick) || !bounded(input.applicationTick, value.tick, MiniSimContracts.TOTAL_TICKS - 1) ||
                !validControl(input.control) || input.applicationTick < previousTick ||
                (input.applicationTick === previousTick && input.sequence <= previousSequence))
                return false;
            previousTick = input.applicationTick;
            previousSequence = input.sequence;
            sequences.add(input.sequence);
        }
        return true;
    }
    MiniSimContracts.validCheckpoint = validCheckpoint;
    function object(value) {
        return !!value && typeof value === 'object' && !Array.isArray(value);
    }
    function keys(value, names) {
        return Object.keys(value).length === names.length && names.every(name => name in value);
    }
    function bounded(value, low, high) {
        return typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high;
    }
    function validControl(value) {
        return object(value) && keys(value, ['target', 'strength', 'motors']) &&
            Array.isArray(value.target) && value.target.length === 2 && value.target.every(x => bounded(x, -Math.PI, Math.PI)) &&
            bounded(value.strength, 1, 20) && typeof value.motors === 'boolean';
    }
    MiniSimContracts.validControl = validControl;
    function validSettings(value) {
        return object(value) && keys(value, ['target', 'strength', 'mass', 'motors', 'gravity']) &&
            validControl({ target: value.target, strength: value.strength, motors: value.motors }) &&
            bounded(value.mass, 0.2, 2) && typeof value.gravity === 'boolean';
    }
    MiniSimContracts.validSettings = validSettings;
    function validEnvelope(value) {
        return object(value) && ['reset', 'start', 'pause', 'step', 'set-control', 'checkpoint', 'restore'].includes(value.type) &&
            keys(value, ['protocol', 'type', 'runId', 'revision', 'sequence', 'applicationTick', 'modelDigest', 'recipeDigest',
                ...(value.type === 'reset' ? ['settings'] : value.type === 'set-control' ? ['control'] : value.type === 'restore' ? ['checkpoint'] : [])]) && value.protocol === MiniSimContracts.PROTOCOL &&
            Number.isSafeInteger(value.runId) && value.runId > 0 &&
            Number.isSafeInteger(value.revision) && value.revision >= 0 &&
            Number.isSafeInteger(value.sequence) && value.sequence > 0 &&
            Number.isSafeInteger(value.applicationTick) && bounded(value.applicationTick, 0, MiniSimContracts.TOTAL_TICKS) &&
            typeof value.modelDigest === 'string' && /^sha256:[a-f0-9]{64}$/.test(value.modelDigest) &&
            typeof value.recipeDigest === 'string' && /^sha256:[a-f0-9]{64}$/.test(value.recipeDigest);
    }
    MiniSimContracts.validEnvelope = validEnvelope;
    function validState(value, tick) {
        return object(value) && Array.isArray(value.q) && Array.isArray(value.velocity) &&
            value.q.length === 2 && value.velocity.length === 2 &&
            [...value.q, ...value.velocity].every(x => bounded(x, -1e6, 1e6)) &&
            typeof value.time === 'number' && Math.abs(value.time - tick * MiniSimContracts.DT) < 1e-10;
    }
    MiniSimContracts.validState = validState;
    // SHA-256 for the compiler's bounded ASCII canonical JSON. This is content
    // identity only; browser-created records are not authenticated evidence.
    function sha256Ascii(text) {
        if (text.length > 8192 || /[^\x00-\x7f]/.test(text))
            throw new Error('Digest input must be bounded ASCII.');
        return sha256Bytes(Uint8Array.from(text, character => character.charCodeAt(0)));
    }
    MiniSimContracts.sha256Ascii = sha256Ascii;
    function sha256Bytes(input) {
        if (!(input instanceof Uint8Array) || input.length > 65536)
            throw new Error('Binary digest input exceeds 64 KiB.');
        const constants = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
        const bytes = new Uint8Array(Math.ceil((input.length + 9) / 64) * 64);
        bytes.set(input);
        bytes[input.length] = 128;
        const data = new DataView(bytes.buffer);
        data.setUint32(bytes.length - 4, input.length * 8);
        const hash = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
        const rotate = (x, n) => (x >>> n) | (x << (32 - n));
        const words = new Int32Array(64);
        for (let offset = 0; offset < bytes.length; offset += 64) {
            for (let i = 0; i < 16; i++)
                words[i] = data.getInt32(offset + i * 4);
            for (let i = 16; i < 64; i++) {
                const x = words[i - 15], y = words[i - 2];
                words[i] = words[i - 16] + (rotate(x, 7) ^ rotate(x, 18) ^ (x >>> 3)) + words[i - 7] + (rotate(y, 17) ^ rotate(y, 19) ^ (y >>> 10));
            }
            let [a, b, c, d, e, f, g, h] = hash;
            for (let i = 0; i < 64; i++) {
                const t1 = (h + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) + ((e & f) ^ (~e & g)) + constants[i] + words[i]) | 0;
                const t2 = ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
                h = g;
                g = f;
                f = e;
                e = (d + t1) | 0;
                d = c;
                c = b;
                b = a;
                a = (t1 + t2) | 0;
            }
            [a, b, c, d, e, f, g, h].forEach((x, i) => { hash[i] = (hash[i] + x) | 0; });
        }
        return 'sha256:' + hash.map(x => (x >>> 0).toString(16).padStart(8, '0')).join('');
    }
    MiniSimContracts.sha256Bytes = sha256Bytes;
    function freeze(value) {
        if (value && typeof value === 'object') {
            Object.values(value).forEach(freeze);
            Object.freeze(value);
        }
        return value;
    }
    function compile(settings) {
        if (!validSettings(settings))
            throw new Error('Unsupported or invalid planar lesson settings.');
        // Deliberately narrow compiler. The recipe declares inertia rather than
        // inferring it from visuals. No arbitrary topology or contact is accepted.
        const parameters = { l1: 0.75, l2: 0.6, m1: 1, m2: settings.mass, gravity: settings.gravity ? 9.81 : 0, damping: 0.12 };
        const descriptor = {
            schema: MiniSimContracts.MODEL_SCHEMA, engine: MiniSimContracts.ENGINE, profile: 'fixed-base-planar-two-link',
            source: { id: 'seedcore-uniform-rod-arm-v1', license: 'Apache-2.0', inertiaRecipe: 'uniform-rod-center-mL2-over-12' },
            frame: { units: 'SI', handedness: 'right', up: 'Y', quaternionOrder: 'xyzw', worldZUpEmbedding: '[x,y,z] -> [x,-z,y]' },
            parameters, nq: 2, nv: 2,
            joints: [{ id: 'shoulder', index: 0, parent: -1, type: 'revolute', axis: [0, 0, 1] },
                { id: 'elbow', index: 1, parent: 0, type: 'revolute', axis: [0, 0, 1] }],
            bodies: [{ id: 'inner-arm', index: 0, joint: 0, center: parameters.l1 / 2, inertia: parameters.m1 * parameters.l1 ** 2 / 12 },
                { id: 'outer-arm', index: 1, joint: 1, center: parameters.l2 / 2, inertia: parameters.m2 * parameters.l2 ** 2 / 12 }],
            capabilities: ['smooth-rk4', 'ideal-torque', 'recorded-playback'],
        };
        const modelDigest = sha256Ascii(JSON.stringify(descriptor));
        const control = { target: [...settings.target], strength: settings.strength, motors: settings.motors };
        const recipe = { schema: 'seedcore.mini-lab.run-recipe.v1', modelDigest, engine: MiniSimContracts.ENGINE,
            controller: 'gravity-compensated-pd-24-5-v1', control, dt: MiniSimContracts.DT, totalTicks: MiniSimContracts.TOTAL_TICKS,
            samplePeriodTicks: MiniSimContracts.CHUNK_TICKS, initial: { q: [15 * Math.PI / 180, 45 * Math.PI / 180], velocity: [0, 0] }, rng: 'none' };
        return freeze({ descriptor, parameters, modelDigest, recipe, recipeDigest: sha256Ascii(JSON.stringify(recipe)) });
    }
    MiniSimContracts.compile = compile;
    function pack(buffer, samples) {
        if (buffer.byteLength !== MiniSimContracts.BUFFER_BYTES || samples.length > 2)
            throw new Error('Invalid snapshot capacity.');
        const data = new Float64Array(buffer);
        data.fill(0);
        samples.forEach((s, i) => data.set([Math.round(s.time / MiniSimContracts.DT), s.time, ...s.q, ...s.velocity], i * 6));
    }
    MiniSimContracts.pack = pack;
    function unpack(buffer, sampleCount) {
        if (buffer.byteLength !== MiniSimContracts.BUFFER_BYTES || !Number.isInteger(sampleCount) || sampleCount < 1 || sampleCount > 2) {
            throw new Error('Invalid snapshot buffer.');
        }
        const data = new Float64Array(buffer), result = [];
        for (let i = 0; i < sampleCount; i++) {
            const [tick, time, q1, q2, v1, v2] = Array.from(data.subarray(i * 6, i * 6 + 6));
            if (![tick, time, q1, q2, v1, v2].every(Number.isFinite) || !Number.isSafeInteger(tick) ||
                tick < 0 || tick > MiniSimContracts.TOTAL_TICKS || tick % MiniSimContracts.CHUNK_TICKS !== 0 || Math.abs(time - tick * MiniSimContracts.DT) > 1e-10) {
                throw new Error('Invalid observation tick or values.');
            }
            result.push({ q: [q1, q2], velocity: [v1, v2], time });
        }
        return result;
    }
    MiniSimContracts.unpack = unpack;
})(MiniSimContracts || (MiniSimContracts = {}));
if (typeof module !== 'undefined')
    module.exports = MiniSimContracts;
