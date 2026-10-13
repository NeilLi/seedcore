#include "mini_tree_physics.h"
#include "mini_physics.h"
#include <cmath>
#include <cassert>
#include <iostream>

namespace {

void close(double x, double y, double tol = 1e-7) {
  assert(std::abs(x - y) < tol);
}

void init_1link(double *b) {
  for (int i = 0; i < 64; i++) b[i] = 0;
  b[0] = 1.0;          // n = 1
  b[1] = 0.8;          // l0 = 0.8m
  b[4] = 1.2;          // m0 = 1.2kg
  b[7] = 0.4;          // c0 = 0.4m
  b[10] = 1.2 * 0.8 * 0.8 / 12.0; // I0
  b[13] = 0.0;         // b0 = 0
  b[16] = 9.81;        // g
  b[17] = 0.2;         // q0
  b[20] = 0.0;         // v0
  b[23] = 0.0;         // t
  b[24] = 0.0;         // tau0
  b[27] = 1.0 / 480.0; // dt
}

void init_2link(double *b) {
  for (int i = 0; i < 64; i++) b[i] = 0;
  b[0] = 2.0;          // n = 2
  b[1] = 0.75; b[2] = 0.6;   // l0, l1
  b[4] = 1.0;  b[5] = 0.7;   // m0, m1
  b[7] = 0.75 / 2.0; b[8] = 0.6 / 2.0; // c0, c1
  b[10] = 1.0 * 0.75 * 0.75 / 12.0; b[11] = 0.7 * 0.6 * 0.6 / 12.0; // I0, I1
  b[13] = 0.12; b[14] = 0.12; // b0, b1
  b[16] = 9.81;        // g
  b[17] = 0.3; b[18] = -0.9; // q0, q1
  b[20] = 0.0; b[21] = 0.0;  // v0, v1
  b[23] = 0.0;         // t
  b[24] = 0.0; b[25] = 0.0;  // tau0, tau1
  b[27] = 1.0 / 480.0; // dt
  b[28] = 0.96; b[29] = -1.22; // target0, target1
  b[31] = 16.0;        // tau_max
  b[32] = 1.0;         // motors
}

void init_3link(double *b) {
  for (int i = 0; i < 64; i++) b[i] = 0;
  b[0] = 3.0;          // n = 3
  b[1] = 0.5; b[2] = 0.4; b[3] = 0.3; // l0, l1, l2
  b[4] = 1.2; b[5] = 0.8; b[6] = 0.5; // m0, m1, m2
  b[7] = 0.25; b[8] = 0.2; b[9] = 0.15; // c0, c1, c2
  b[10] = 1.2 * 0.5 * 0.5 / 12.0;
  b[11] = 0.8 * 0.4 * 0.4 / 12.0;
  b[12] = 0.5 * 0.3 * 0.3 / 12.0;
  b[13] = 0.05; b[14] = 0.05; b[15] = 0.05; // b0, b1, b2
  b[16] = 9.81;        // g
  b[17] = 0.4; b[18] = -0.6; b[19] = 0.3; // q0, q1, q2
  b[20] = 0.0; b[21] = 0.0; b[22] = 0.0;  // v0, v1, v2
  b[23] = 0.0;         // t
  b[24] = 0.0; b[25] = 0.0; b[26] = 0.0;  // tau
  b[27] = 1.0 / 480.0; // dt
  b[28] = 0.8; b[29] = -0.5; b[30] = 0.2; // target
  b[31] = 15.0;        // tau_max
  b[32] = 1.0;         // motors
}

void step_tree(double *b, int count, int op = 2) {
  for (int s = 0; s < count; s++) {
    assert(mini_tree_eval(op, b, 64) == 0);
    int n = static_cast<int>(b[0]);
    for (int j = 0; j < n; j++) {
      b[17 + j] = b[34 + j];
      b[20 + j] = b[37 + j]; // v_next is at 37 for n=3 (or 34+n)
    }
    b[23] = b[40];
  }
}

} // namespace

int main() {
  std::cout << "Starting SIM-3 tree physics invariant verification...\n";

  // ==========================================
  // Test Group 1: 1-Link Pendulum Verification
  // ==========================================
  {
    double b[64] = {};
    init_1link(b);

    // Forward kinematics length check
    assert(mini_tree_eval(3, b, 64) == 0);
    close(b[34], 0.0); close(b[35], 0.0);
    close(std::hypot(b[36], b[37]), b[1]);

    // Inertia check: single body M00 = I0 + m0 * c0^2
    assert(mini_tree_eval(0, b, 64) == 0);
    double expected_M = b[10] + b[4] * b[7] * b[7];
    close(b[34], expected_M);

    // Gravity torque: g0 = m0 * g * c0 * cos(q0)
    double expected_g = b[4] * b[16] * b[7] * std::cos(b[17]);
    close(b[43], expected_g);

    // Unforced conservation of energy
    b[20] = 0.5; // initial velocity
    assert(mini_tree_eval(4, b, 64) == 0);
    double e_initial = b[36];

    for (int t = 0; t < 960; t++) {
      assert(mini_tree_eval(2, b, 64) == 0);
      b[17] = b[34];
      b[20] = b[37];
      b[23] = b[40];
    }
    assert(mini_tree_eval(4, b, 64) == 0);
    close(b[36], e_initial, 1e-5);
  }
  std::cout << "  ✔ 1-link pendulum forward kinematics, inertia, and energy conservation passed\n";

  // ==========================================
  // Test Group 2: 2-Link Exact Match with SIM-2 Reference
  // ==========================================
  {
    double tb[64] = {};
    init_2link(tb);

    double sb[32] = {0.75, 0.6, 1.0, 0.7, 9.81, 0.12, 0.3, -0.9, 0, 0, 0, 0, 0, 1.0/480.0, 0.96, -1.22, 16, 1};

    // Forward kinematics comparison
    assert(mini_tree_eval(3, tb, 64) == 0);
    assert(mini_eval(3, sb, 32) == 0);
    close(tb[36], sb[20], 1e-12);
    close(tb[37], sb[21], 1e-12);
    close(tb[38], sb[22], 1e-12);
    close(tb[39], sb[23], 1e-12);

    // Terms comparison (M, c, g)
    assert(mini_tree_eval(0, tb, 64) == 0);
    assert(mini_eval(0, sb, 32) == 0);
    // M00, M01, M11
    close(tb[34], sb[20], 1e-12);
    close(tb[35], sb[21], 1e-12);
    close(tb[37], sb[22], 1e-12);
    // Coriolis c0, c1
    close(tb[40], sb[23], 1e-12);
    close(tb[41], sb[24], 1e-12);
    // Gravity g0, g1
    close(tb[43], sb[25], 1e-12);
    close(tb[44], sb[26], 1e-12);

    // Energy comparison
    assert(mini_tree_eval(4, tb, 64) == 0);
    assert(mini_eval(4, sb, 32) == 0);
    close(tb[34], sb[20], 1e-12); // K
    close(tb[35], sb[21], 1e-12); // U
    close(tb[36], sb[22], 1e-12); // Total

    // Acceleration with applied torque
    tb[24] = 1.5; tb[25] = -0.8;
    sb[11] = 1.5; sb[12] = -0.8;
    assert(mini_tree_eval(1, tb, 64) == 0);
    assert(mini_eval(1, sb, 32) == 0);
    close(tb[34], sb[20], 1e-12);
    close(tb[35], sb[21], 1e-12);
  }
  std::cout << "  ✔ 2-link exact numerical parity with SIM-2 reference (< 1e-12 error) passed\n";

  // ==========================================
  // Test Group 3: 3-Link Dynamics & Mathematics
  // ==========================================
  {
    double b[64] = {};
    init_3link(b);

    // 1. Forward Kinematics distance checks
    assert(mini_tree_eval(3, b, 64) == 0);
    close(std::hypot(b[36] - b[34], b[37] - b[35]), b[1]);
    close(std::hypot(b[38] - b[36], b[39] - b[37]), b[2]);
    close(std::hypot(b[40] - b[38], b[41] - b[39]), b[3]);

    // 2. Mass Matrix Symmetry and Positive-Definiteness across joint angles
    for (double q0 = -2.5; q0 <= 2.5; q0 += 1.0) {
      for (double q1 = -2.0; q1 <= 2.0; q1 += 1.0) {
        for (double q2 = -2.0; q2 <= 2.0; q2 += 1.0) {
          b[17] = q0; b[18] = q1; b[19] = q2;
          assert(mini_tree_eval(0, b, 64) == 0);
          double M00 = b[34], M01 = b[35], M02 = b[36];
          double M11 = b[37], M12 = b[38], M22 = b[39];

          // Diagonal entries positive
          assert(M00 > 0 && M11 > 0 && M22 > 0);

          // 2x2 leading principal minor
          double det2 = M00 * M11 - M01 * M01;
          assert(det2 > 1e-10);

          // 3x3 determinant
          double det3 = M00 * (M11 * M22 - M12 * M12) -
                        M01 * (M01 * M22 - M12 * M02) +
                        M02 * (M01 * M12 - M11 * M02);
          assert(det3 > 1e-10);
        }
      }
    }

    // 3. Potential energy gradient equals gravity vector (dU/dq_i = g_i)
    init_3link(b);
    assert(mini_tree_eval(0, b, 64) == 0);
    double g_vec[3] = {b[43], b[44], b[45]};

    for (int j = 0; j < 3; j++) {
      b[17 + j] += 1e-6;
      assert(mini_tree_eval(4, b, 64) == 0);
      double u_plus = b[35];

      b[17 + j] -= 2e-6;
      assert(mini_tree_eval(4, b, 64) == 0);
      double u_minus = b[35];

      b[17 + j] += 1e-6; // restore
      double num_grad = (u_plus - u_minus) / 2e-6;
      close(num_grad, g_vec[j], 1e-6);
    }

    // 4. End-effector Jacobian finite difference agreement
    init_3link(b);
    assert(mini_tree_eval(5, b, 64) == 0);
    double Jx[3] = {b[34], b[35], b[36]};
    double Jy[3] = {b[37], b[38], b[39]};

    assert(mini_tree_eval(3, b, 64) == 0);
    double tip_x0 = b[40], tip_y0 = b[41];

    for (int j = 0; j < 3; j++) {
      b[17 + j] += 1e-6;
      assert(mini_tree_eval(3, b, 64) == 0);
      double dx = (b[40] - tip_x0) / 1e-6;
      double dy = (b[41] - tip_y0) / 1e-6;
      b[17 + j] -= 1e-6; // restore
      close(dx, Jx[j], 1e-6);
      close(dy, Jy[j], 1e-6);
    }

    // 5. Unforced conservation of energy (b = 0, tau = 0)
    init_3link(b);
    b[13] = 0; b[14] = 0; b[15] = 0; // zero damping
    b[20] = 0.5; b[21] = -0.3; b[22] = 0.2; // initial velocities
    assert(mini_tree_eval(4, b, 64) == 0);
    double e_start = b[36];

    for (int t = 0; t < 1920; t++) {
      assert(mini_tree_eval(2, b, 64) == 0);
      b[17] = b[34]; b[18] = b[35]; b[19] = b[36];
      b[20] = b[37]; b[21] = b[38]; b[22] = b[39];
      b[23] = b[40];
    }
    assert(mini_tree_eval(4, b, 64) == 0);
    close(b[36], e_start, 1e-4);

    // 6. Viscous damping energy dissipation
    init_3link(b);
    b[13] = 0.2; b[14] = 0.2; b[15] = 0.2; // positive damping
    b[20] = 0.5; b[21] = -0.3; b[22] = 0.2;
    assert(mini_tree_eval(4, b, 64) == 0);
    double e_initial_damped = b[36];

    for (int t = 0; t < 960; t++) {
      assert(mini_tree_eval(2, b, 64) == 0);
      b[17] = b[34]; b[18] = b[35]; b[19] = b[36];
      b[20] = b[37]; b[21] = b[38]; b[22] = b[39];
      b[23] = b[40];
    }
    assert(mini_tree_eval(4, b, 64) == 0);
    assert(b[36] < e_initial_damped);
  }
  std::cout << "  ✔ 3-link mass symmetry, positive definiteness, Jacobian, and energy laws passed\n";

  // ==========================================
  // Test Group 4: Invalid Parameter Rejection
  // ==========================================
  {
    double b[64] = {};
    init_3link(b);

    // Negative mass rejected
    b[4] = -1.0; assert(mini_tree_eval(0, b, 64) == 1); b[4] = 1.2;

    // Zero length rejected
    b[1] = 0.0; assert(mini_tree_eval(0, b, 64) == 1); b[1] = 0.5;

    // COM outside length rejected
    b[7] = 0.6; assert(mini_tree_eval(0, b, 64) == 1); b[7] = 0.25;

    // Invalid link count rejected
    b[0] = 4.0; assert(mini_tree_eval(0, b, 64) == 1);
    b[0] = 0.0; assert(mini_tree_eval(0, b, 64) == 1);
    b[0] = 3.0;

    // Invalid buffer length rejected
    assert(mini_tree_eval(0, b, 63) == 1);
    assert(mini_tree_eval(0, nullptr, 64) == 1);
  }
  std::cout << "  ✔ Invalid model parameter & boundary rejection passed\n";

  std::cout << "All SIM-3 native invariant test groups passed successfully!\n";
  return 0;
}
