"""Compile typed primitive robot drafts into asset-free MJCF."""

from xml.etree.ElementTree import Element, SubElement, tostring

from .contracts import RobotSpec


def build_mjcf(robot: RobotSpec) -> str:
    root = Element("mujoco", model=robot.name)
    SubElement(root, "compiler", angle="radian", autolimits="true")
    SubElement(
        root,
        "option",
        timestep=str(robot.timestep_s),
        gravity=f"0 0 {-robot.gravity_m_s2}",
        integrator="implicitfast",
    )
    default = SubElement(root, "default")
    SubElement(default, "geom", friction=f"{robot.friction} 0.005 0.0001")
    world = SubElement(root, "worldbody")
    SubElement(world, "light", pos="0 0 3", dir="0 0 -1")
    SubElement(
        world, "geom", name="floor", type="plane", size="3 3 0.1", rgba="0.3 0.35 0.4 1"
    )
    base = SubElement(world, "body", name="base", pos=f"0 0 {robot.base_height_m}")
    if robot.floating_base:
        SubElement(base, "freejoint", name="base_free")
    size = str(robot.base_half_size_m)
    SubElement(
        base,
        "geom",
        name="base_geom",
        type="box",
        size=f"{size} {size} {size}",
        mass=str(robot.base_mass_kg),
        rgba="0.3 0.4 0.8 1",
    )
    parent = base
    actuators = SubElement(root, "actuator")
    sensors = SubElement(root, "sensor")
    contacts = SubElement(root, "contact")
    axes = {"x": "1 0 0", "y": "0 1 0", "z": "0 0 1"}
    for i, link in enumerate(robot.links):
        # The primitive capsules overlap at a hinge. Adjacent-body collision
        # geometry does not represent the mechanical joint housing.
        SubElement(
            contacts,
            "exclude",
            body1="base" if i == 0 else f"link_{i - 1}",
            body2=f"link_{i}",
        )
        offset = robot.base_half_size_m if i == 0 else robot.links[i - 1].length_m
        body = SubElement(parent, "body", name=f"link_{i}", pos=f"{offset} 0 0")
        SubElement(
            body,
            "joint",
            name=f"joint_{i}",
            type="hinge",
            axis=axes[link.axis],
            range=f"{link.lower_rad} {link.upper_rad}",
            damping=str(link.damping),
        )
        SubElement(
            body,
            "geom",
            name=f"link_geom_{i}",
            type="capsule",
            fromto=f"0 0 0 {link.length_m} 0 0",
            size=str(link.radius_m),
            mass=str(link.mass_kg),
            rgba="0.2 0.75 0.6 1",
        )
        limit = str(link.torque_limit_nm)
        SubElement(
            actuators,
            "motor",
            name=f"motor_{i}",
            joint=f"joint_{i}",
            gear="1",
            ctrllimited="true",
            ctrlrange=f"-{limit} {limit}",
            forcelimited="true",
            forcerange=f"-{limit} {limit}",
        )
        SubElement(sensors, "jointpos", name=f"encoder_{i}", joint=f"joint_{i}")
        SubElement(sensors, "jointvel", name=f"velocity_{i}", joint=f"joint_{i}")
        parent = body
    tip_x = robot.links[-1].length_m if robot.links else 0.0
    SubElement(parent, "site", name="tip", pos=f"{tip_x} 0 0", size="0.008")
    SubElement(sensors, "framepos", name="tip_position", objtype="site", objname="tip")
    SubElement(base, "site", name="imu", size="0.005")
    SubElement(sensors, "gyro", name="base_gyro", site="imu")
    SubElement(sensors, "accelerometer", name="base_accelerometer", site="imu")
    return tostring(root, encoding="unicode")
