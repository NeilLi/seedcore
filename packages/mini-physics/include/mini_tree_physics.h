#ifndef SEEDCORE_MINI_TREE_PHYSICS_H
#define SEEDCORE_MINI_TREE_PHYSICS_H

#ifdef __cplusplus
extern "C" {
#endif

/* SeedCore Mini Physics - SIM-3 Tree Dynamics ABI
 * ABI 2, zero allocation, no exceptions or retained pointers.
 * Caller owns a 64-double buffer.
 *
 * Buffer layout:
 * Input parameters:
 *   [0]: num_links (1, 2, or 3)
 *   [1..3]: l[0..2]  - link lengths (m)
 *   [4..6]: m[0..2]  - link masses (kg)
 *   [7..9]: c[0..2]  - center-of-mass offsets from joint (m)
 *   [10..12]: I[0..2] - link moments of inertia about COM (kg*m^2)
 *   [13..15]: b[0..2] - joint viscous damping (N*m*s/rad)
 *   [16]: gravity g (m/s^2)
 * State:
 *   [17..19]: q[0..2] - joint angles (rad)
 *   [20..22]: v[0..2] - joint angular velocities (rad/s)
 *   [23]: time t (s)
 * Control & Step:
 *   [24..26]: tau[0..2] - applied motor torques (N*m)
 *   [27]: dt - timestep (s)
 *   [28..30]: target[0..2] - target joint angles for PD control (rad)
 *   [31]: tau_max - maximum torque magnitude limit (N*m)
 *   [32]: motors - motor enable switch (1.0 = enabled, 0.0 = disabled)
 *
 * Outputs start at index 34:
 *   Operation 0 (Terms):
 *     [34..39]: M matrix (symmetric unique: M00, M01, M02, M11, M12, M22)
 *     [40..42]: Coriolis & centrifugal vector c[0..2]
 *     [43..45]: Gravity torque vector g[0..2]
 *   Operation 1 (Acceleration):
 *     [34..36]: q_ddot[0..2] = M^-1 * (tau - c - g - b*v)
 *   Operation 2 (RK4 Step):
 *     [34..36]: q_next[0..2]
 *     [37..39]: v_next[0..2]
 *     [40]: t_next
 *   Operation 3 (Forward Kinematics):
 *     [34..35]: origin (0, 0)
 *     [36..37]: joint 1 pos (x1, y1)
 *     [38..39]: joint 2 pos (x2, y2) (or tip if num_links==2)
 *     [40..41]: tip pos (x_tip, y_tip)
 *   Operation 4 (Energy):
 *     [34]: Kinetic energy K
 *     [35]: Potential energy U
 *     [36]: Total mechanical energy E = K + U
 *   Operation 5 (Jacobian):
 *     [34..36]: J_x row (dx_tip/dq0, dx_tip/dq1, dx_tip/dq2)
 *     [37..39]: J_y row (dy_tip/dq0, dy_tip/dq1, dy_tip/dq2)
 *   Operation 6 (Controlled Step):
 *     [34..36]: q_next[0..2]
 *     [37..39]: v_next[0..2]
 *     [40]: t_next
 *     [41..43]: applied_tau[0..2]
 *
 * Return codes:
 *   0: OK
 *   1: Invalid input, length, op, or parameters (non-finite, negative mass/length)
 *   2: Singular mass matrix (det <= 1e-14)
 *   3: Numerical divergence / non-finite state
 *
 * On failure, output buffer remains unchanged.
 */
int mini_tree_eval(int operation, double *buffer, unsigned length);
double *mini_tree_scratch(void);
unsigned mini_tree_abi(void);

#ifdef __cplusplus
}
#endif

#endif /* SEEDCORE_MINI_TREE_PHYSICS_H */
