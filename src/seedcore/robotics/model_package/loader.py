"""Verify a local inventory, then compile exclusively from verified asset bytes.

This is an offline development boundary, not an OS sandbox or hardware gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Any
import xml.etree.ElementTree as ET

from pydantic import ValidationError

from .contracts import ModelPackage, package_path

MAX_XML_BYTES = 2 * 1024 * 1024
MAX_XML_ELEMENTS = 10000


class ModelPackageError(ValueError):
    """Manifest, integrity, unsupported input or compiled parity failure."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(root: Path, relative: str, limit: int) -> bytes:
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise ModelPackageError(f"symlinks are not package files: {relative}")
    try:
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ModelPackageError(f"missing or nonregular package file: {relative}")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ModelPackageError(f"cannot read package file: {relative}") from exc
    if len(data) > limit:
        raise ModelPackageError(f"package file exceeds size limit: {relative}")
    return data


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelPackageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class VerifiedModelPackage:
    manifest: ModelPackage
    manifest_sha256: str
    package_sha256: str
    files: Mapping[str, bytes]


@dataclass(frozen=True)
class LoadedModelPackage:
    package: VerifiedModelPackage
    model: Any
    report: dict


def verify_model_package(
    manifest_path: str | Path, *, expected_manifest_sha256: str | None = None
) -> VerifiedModelPackage:
    """Read and hash once; no network, native engine, or source-checkout dependency."""
    path = Path(manifest_path).absolute()
    root = path.parent.resolve()
    raw = _read(root, path.name, MAX_XML_BYTES)
    manifest_sha = _sha(raw)
    if (
        expected_manifest_sha256 is not None
        and manifest_sha != expected_manifest_sha256
    ):
        raise ModelPackageError("manifest SHA-256 does not match caller pin")
    try:
        manifest = ModelPackage.model_validate(
            json.loads(raw, object_pairs_hook=_no_duplicate_keys)
        )
    except (ValidationError, ValueError, UnicodeError) as exc:
        raise ModelPackageError(f"invalid model-package manifest: {exc}") from exc
    files = {}
    for file in manifest.files:
        data = _read(root, file.path, file.size_bytes)
        if len(data) != file.size_bytes or _sha(data) != file.sha256:
            raise ModelPackageError(f"size or SHA-256 mismatch: {file.path}")
        files[file.path] = data
    canonical = manifest.model_dump(mode="json")
    canonical["files"] = sorted(canonical["files"], key=lambda file: file["path"])
    digest = _sha(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )
    return VerifiedModelPackage(manifest, manifest_sha, digest, MappingProxyType(files))


def _prepare_xml(package: VerifiedModelPackage) -> tuple[str, dict[str, bytes]]:
    """Expand includes and rewrite resources to flat VFS names before native parsing.

    Includes and compiler directories are relative to the main XML directory,
    as in MuJoCo. Every native resource reference must use a verified VFS key.
    """
    manifest = package.manifest
    roles = {file.path: file.role for file in manifest.files}
    base = PurePosixPath(manifest.entrypoint).parent
    included = {manifest.entrypoint}
    element_count = 0

    def reference(value: str, directory: str = "") -> str:
        try:
            package_path(value)
            if directory:
                package_path(directory)
            result = str(base / directory / value)
            package_path(result)
        except ValueError as exc:
            raise ModelPackageError(str(exc)) from exc
        if result not in package.files:
            raise ModelPackageError(f"undeclared XML dependency: {result}")
        return result

    def parse(name: str, depth: int = 0) -> ET.Element:
        nonlocal element_count
        if depth > 32 or roles[name] != "model":
            raise ModelPackageError("include depth or model-file role violation")
        data = package.files[name]
        if len(data) > MAX_XML_BYTES:
            raise ModelPackageError("XML exceeds 2 MiB")
        try:
            text = data.decode("utf-8")
            if (
                "<!DOCTYPE" in text.upper()
                or "<!ENTITY" in text.upper()
                or "\x00" in text
            ):
                raise ModelPackageError(
                    "DTD, entities and non-UTF-8 XML are unsupported"
                )
            node = ET.fromstring(text)
        except (ET.ParseError, UnicodeError) as exc:
            raise ModelPackageError(f"invalid UTF-8 XML: {name}") from exc
        element_count += sum(1 for _ in node.iter())
        if element_count > MAX_XML_ELEMENTS:
            raise ModelPackageError("XML exceeds element budget")

        parents = [node]
        while parents:
            parent = parents.pop()
            for child in list(parent):
                if child.tag == "include":
                    if (
                        manifest.format != "mjcf"
                        or set(child.attrib) != {"file"}
                        or len(child)
                    ):
                        raise ModelPackageError("unsupported include")
                    dependency = reference(child.attrib["file"])
                    if dependency in included:
                        raise ModelPackageError(
                            f"duplicate or cyclic include: {dependency}"
                        )
                    included.add(dependency)
                    fragment = parse(dependency, depth + 1)
                    if not len(fragment):
                        raise ModelPackageError("empty include")
                    index = list(parent).index(child)
                    parent.remove(child)
                    for offset, item in enumerate(fragment):
                        parent.insert(index + offset, item)
                else:
                    parents.append(child)
        return node

    root = parse(manifest.entrypoint)
    if root.tag != ("mujoco" if manifest.format == "mjcf" else "robot"):
        raise ModelPackageError("entrypoint root does not match manifest format")
    compilers = list(root.iter("compiler"))
    if len(compilers) > 1:
        raise ModelPackageError("multiple compiler elements are unsupported")
    compiler = compilers[0] if compilers else None
    directories = dict(compiler.attrib) if compiler is not None else {}
    for key in ("meshdir", "texturedir", "assetdir"):
        if directories.get(key):
            try:
                package_path(directories[key])
            except ValueError as exc:
                raise ModelPackageError(str(exc)) from exc
            compiler.attrib[key] = ""
    strip = (
        directories.get("strippath", "true" if manifest.format == "urdf" else "false")
        == "true"
    )
    if compiler is not None:
        compiler.set("strippath", "false")
    assets = {}
    forbidden = {
        "plugin",
        "extension",
        "attach",
        "model",
        "composite",
        "flexcomp",
        "replicate",
    }
    allowed_file_tags = {
        "mesh": "mesh",
        "texture": "texture",
        "hfield": "heightfield",
        "skin": "skin",
    }
    for node in root.iter():
        if node.tag in forbidden or not isinstance(node.tag, str) or "{" in node.tag:
            raise ModelPackageError(f"unsupported XML element: {node.tag}")
        for key, value in list(node.attrib.items()):
            if key.startswith("file"):
                if node.tag not in allowed_file_tags or key not in {
                    "file",
                    "filename",
                    "fileleft",
                    "fileright",
                    "fileup",
                    "filedown",
                    "filefront",
                    "fileback",
                }:
                    raise ModelPackageError(
                        f"unsupported file reference: {node.tag}.{key}"
                    )
                # Validate before stripping, so absolute paths/URIs cannot be hidden.
                try:
                    package_path(value)
                except ValueError as exc:
                    raise ModelPackageError(str(exc)) from exc
                name = PurePosixPath(value).name if strip else value
                directory = ""
                if node.tag in {"mesh", "hfield", "skin"}:
                    directory = directories.get(
                        "meshdir", directories.get("assetdir", "")
                    )
                elif node.tag == "texture":
                    directory = directories.get(
                        "texturedir", directories.get("assetdir", "")
                    )
                dependency = reference(name, directory)
                if roles[dependency] != allowed_file_tags[node.tag]:
                    raise ModelPackageError(f"asset role mismatch: {dependency}")
                vfs_name = _sha(dependency.encode()) + PurePosixPath(dependency).suffix
                assets[vfs_name] = package.files[dependency]
                if (
                    manifest.format == "mjcf"
                    and key == "file"
                    and "name" not in node.attrib
                ):
                    node.set("name", PurePosixPath(value).stem)
                node.set(key, vfs_name)
    return ET.tostring(root, encoding="unicode"), assets


def _validate_parity(mj, model, manifest: ModelPackage) -> dict:
    import numpy as np

    expected = manifest.parity

    def fail(label: str):
        raise ModelPackageError(f"compiled model parity mismatch: {label}")

    def name(kind, index):
        value = mj.mj_id2name(model, kind, index)
        if value is None:
            fail("unnamed body, joint or actuator")
        return value

    if (model.nq, model.nv, model.nbody, model.njnt, model.nu) != (
        expected.nq,
        expected.nv,
        len(expected.bodies) + 1,
        len(expected.joints),
        len(expected.actuators),
    ):
        fail("dimensions")
    mass = float(model.body_mass.sum())
    if not math.isclose(
        mass, expected.total_mass_kg, rel_tol=0, abs_tol=expected.mass_tolerance_kg
    ):
        fail("total mass")
    if not math.isclose(
        float(model.opt.timestep), expected.timestep_s, rel_tol=0, abs_tol=1e-12
    ):
        fail("timestep")
    body_names = [name(mj.mjtObj.mjOBJ_BODY, i) for i in range(model.nbody)]
    for i, body in enumerate(expected.bodies, start=1):
        if (body_names[i], body_names[int(model.body_parentid[i])]) != (
            body.name,
            body.parent,
        ):
            fail(f"body tree: {body.name}")
    types = {
        "free": mj.mjtJoint.mjJNT_FREE,
        "ball": mj.mjtJoint.mjJNT_BALL,
        "slide": mj.mjtJoint.mjJNT_SLIDE,
        "hinge": mj.mjtJoint.mjJNT_HINGE,
    }
    joint_names = [name(mj.mjtObj.mjOBJ_JOINT, i) for i in range(model.njnt)]

    def check_range(limited, actual, desired, label):
        if bool(limited) != (desired is not None):
            fail(label)
        if desired is not None and not np.allclose(actual, desired, rtol=0, atol=1e-8):
            fail(label)

    for i, joint in enumerate(expected.joints):
        if (
            joint_names[i],
            body_names[int(model.jnt_bodyid[i])],
            model.jnt_type[i],
        ) != (joint.name, joint.body, types[joint.type]):
            fail(f"joint mapping: {joint.name}")
        check_range(
            model.jnt_limited[i],
            model.jnt_range[i],
            joint.range,
            f"joint range: {joint.name}",
        )
    for i, actuator in enumerate(expected.actuators):
        if model.actuator_trntype[i] != mj.mjtTrn.mjTRN_JOINT:
            fail(f"unsupported transmission: {actuator.name}")
        joint_id = int(model.actuator_trnid[i, 0])
        if (name(mj.mjtObj.mjOBJ_ACTUATOR, i), joint_names[joint_id]) != (
            actuator.name,
            actuator.joint,
        ):
            fail(f"actuator mapping: {actuator.name}")
        if not np.allclose(model.actuator_gear[i], actuator.gear, rtol=0, atol=1e-8):
            fail(f"actuator gear: {actuator.name}")
        check_range(
            model.actuator_ctrllimited[i],
            model.actuator_ctrlrange[i],
            actuator.control_range,
            f"control range: {actuator.name}",
        )
        check_range(
            model.actuator_forcelimited[i],
            model.actuator_forcerange[i],
            actuator.force_range,
            f"force range: {actuator.name}",
        )
    data = mj.MjData(model)
    mj.mj_forward(model, data)
    if any(w.number for w in data.warning) or not all(
        np.isfinite(x).all()
        for x in (data.qpos, data.qvel, data.qacc, data.xpos, data.xquat)
    ):
        fail("initial forward kinematics")
    return {
        "total_mass_kg": mass,
        "dimensions": {
            "nq": model.nq,
            "nv": model.nv,
            "nu": model.nu,
            "nbody": model.nbody,
        },
        "joint_names": joint_names,
        "body_names": body_names,
        "timestep_s": float(model.opt.timestep),
        "checks": {
            "mass": True,
            "joint_ranges": True,
            "actuator_mapping": True,
            "body_tree": True,
            "forward_kinematics": True,
        },
    }


def load_model_package(
    manifest_path: str | Path, *, expected_manifest_sha256: str | None = None
) -> LoadedModelPackage:
    """Return a fresh native model only after integrity and parity succeed."""
    from seedcore.robotics.mujoco_workbench.runtime import PROFILE, require_engine

    package = verify_model_package(
        manifest_path, expected_manifest_sha256=expected_manifest_sha256
    )
    xml, assets = _prepare_xml(package)
    mj = require_engine()
    try:
        model = mj.MjModel.from_xml_string(xml, assets=assets)
    except ValueError as exc:
        raise ModelPackageError(f"MuJoCo compilation failed: {exc}") from exc
    report = _validate_parity(mj, model, package.manifest)
    report.update(
        profile=PROFILE,
        engine="mujoco",
        engine_version=mj.__version__,
        package_id=package.manifest.package_id,
        version=package.manifest.version,
        manifest_sha256=package.manifest_sha256,
        package_sha256=package.package_sha256,
        source=package.manifest.source.model_dump(mode="json"),
        claim="Offline model integrity and compiled parity only; no physical acceptance or execution authority.",
    )
    return LoadedModelPackage(package, model, report)
