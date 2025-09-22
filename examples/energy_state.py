import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (required for 3D projection)

# -------- Parameters --------
# Landscape grid
x = np.linspace(-10, 10, 300)
y = np.linspace(-10, 10, 300)
X, Y = np.meshgrid(x, y)

# Define a multi-well potential energy function in 2D (sum of negative Gaussians)
def energy_landscape_2d(X, Y):
    # (center_x, center_y, width_x, width_y)
    wells = [
        (-3.0, -2.0, 2.0, 1.5),  # quantum-ish
        (0.0,  2.5, 1.2, 1.2),   # memory attractor
        (4.0, -1.0, 2.5, 2.0)    # cosmic/gravity-like
    ]
    Z = np.zeros_like(X, dtype=float)
    for cx, cy, wx, wy in wells:
        Z -= np.exp(-0.5 * (((X - cx) / wx) ** 2 + ((Y - cy) / wy) ** 2))
    return Z

Z = energy_landscape_2d(X, Y)

# -------- Plot --------
fig = plt.figure(figsize=(10, 7))
ax = fig.add_subplot(111, projection="3d")

# 3D surface (default colormap and shading per instructions)
surf = ax.plot_surface(X, Y, Z, linewidth=0, antialiased=True)

# Mark representative wells (centers)
well_points = np.array([
    [-3.0, -2.0],
    [0.0,  2.5],
    [4.0, -1.0]
])
for (cx, cy) in well_points:
    # Sample Z at the grid point closest to (cx, cy)
    ix = (np.abs(x - cx)).argmin()
    iy = (np.abs(y - cy)).argmin()
    zc = Z[iy, ix]
    ax.scatter(cx, cy, zc, s=40)             # default styling
    ax.text(cx, cy, zc - 0.3, "well", ha="center", va="top")

# Labels and title
ax.set_title("Energy Landscape (3D): Cosmic, Quantum, and Cognitive Wells")
ax.set_xlabel("State dimension $s_{t,1}$")
ax.set_ylabel("State dimension $s_{t,2}$")
ax.set_zlabel("Energy $E(s_t)$")

# View angle
ax.view_init(elev=30, azim=135)

plt.tight_layout()
plt.show()

