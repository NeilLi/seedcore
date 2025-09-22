import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # Required for 3D projection

# -------- Parameters --------
# Landscape grid
x = np.linspace(-10, 10, 300)
y = np.linspace(-10, 10, 300)
X, Y = np.meshgrid(x, y)

# Define a multi-well potential energy function in 2D (sum of negative Gaussians)
def energy_landscape_2d(X, Y):
    """
    Creates an energy surface with three distinct wells.
    Each well is a negative Gaussian function, representing a stable state.
    """
    # Parameters for each well: (center_x, center_y, width_x, width_y)
    wells = [
        (-3.0, -2.0, 2.0, 1.5),  # Quantum-like well
        (0.0,  2.5, 1.2, 1.2),   # Memory attractor well
        (4.0, -1.0, 2.5, 2.0)    # Cosmic/gravity-like well
    ]
    
    Z = np.zeros_like(X, dtype=float)
    for cx, cy, wx, wy in wells:
        # Add a negative Gaussian for each well
        Z -= np.exp(-0.5 * (((X - cx) / wx) ** 2 + ((Y - cy) / wy) ** 2))
        
    return Z

# Calculate the energy values (Z) for the entire grid
Z = energy_landscape_2d(X, Y)

# -------- Plotting --------
fig = plt.figure(figsize=(10, 7))
ax = fig.add_subplot(111, projection="3d")

# Plot the 3D surface
# 'linewidth=0' and 'antialiased=True' create a smooth surface
surf = ax.plot_surface(X, Y, Z, cmap='viridis', linewidth=0, antialiased=True)

# Mark the center of each well for clarity
well_points = np.array([
    [-3.0, -2.0],
    [0.0,  2.5],
    [4.0, -1.0]
])

for (cx, cy) in well_points:
    # Find the energy value at the grid point closest to the well's center
    ix = (np.abs(x - cx)).argmin()
    iy = (np.abs(y - cy)).argmin()
    zc = Z[iy, ix]
    
    # Place a marker and a label at the bottom of each well
    ax.scatter(cx, cy, zc, s=50, c='red', depthshade=True)
    ax.text(cx, cy, zc - 0.3, "well", color='white', ha="center", va="top")

# Set labels and title using LaTeX for mathematical notation
ax.set_title("Energy Landscape: Cosmic, Quantum, and Cognitive Wells")
ax.set_xlabel("State dimension $s_{t,1}$")
ax.set_ylabel("State dimension $s_{t,2}$")
ax.set_zlabel("Energy $E(s_t)$")

# Set the viewing angle for a clear perspective
ax.view_init(elev=30, azim=135)

plt.tight_layout()
plt.show()
