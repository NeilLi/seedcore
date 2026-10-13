#include "mini_tree_physics.h"

#ifdef __wasm__
extern "C" double sin(double);
extern "C" double cos(double);
#else
#include <cmath>
using std::sin;
using std::cos;
#endif

namespace {

bool finite(double x) { return __builtin_isfinite(x); }
double absval(double x) { return x < 0 ? -x : x; }

struct TreeParams {
  int n;
  double l[3];
  double m[3];
  double c[3];
  double I[3];
  double b[3];
  double g;
};

bool parse_params(const double *buf, TreeParams &p) {
  int n = static_cast<int>(buf[0]);
  if (n < 1 || n > 3) return false;
  p.n = n;
  for (int i = 0; i < n; i++) {
    p.l[i] = buf[1 + i];
    p.m[i] = buf[4 + i];
    p.c[i] = buf[7 + i];
    p.I[i] = buf[10 + i];
    p.b[i] = buf[13 + i];
    if (!finite(p.l[i]) || p.l[i] <= 0 || p.l[i] > 10.0) return false;
    if (!finite(p.m[i]) || p.m[i] <= 0 || p.m[i] > 100.0) return false;
    if (!finite(p.c[i]) || p.c[i] < 0 || p.c[i] > p.l[i]) return false;
    if (!finite(p.I[i]) || p.I[i] <= 0 || p.I[i] > 100.0) return false;
    if (!finite(p.b[i]) || p.b[i] < 0 || p.b[i] > 100.0) return false;
  }
  p.g = buf[16];
  if (!finite(p.g) || p.g < 0 || p.g > 100.0) return false;
  return true;
}

// Compute forward terms: M(q), c(q, v), g(q)
void tree_terms(const TreeParams &p, const double *q, const double *v,
                double M[3][3], double c[3], double g_vec[3]) {
  int n = p.n;
  double phi[3];
  phi[0] = q[0];
  for (int i = 1; i < n; i++) phi[i] = phi[i - 1] + q[i];

  double cos_phi[3], sin_phi[3];
  for (int i = 0; i < n; i++) {
    cos_phi[i] = cos(phi[i]);
    sin_phi[i] = sin(phi[i]);
  }

  // Jvx and Jvy for each link's center of mass
  double Jvx[3][3] = {};
  double Jvy[3][3] = {};
  for (int i = 0; i < n; i++) {
    for (int j = 0; j <= i; j++) {
      double sum_x = 0, sum_y = 0;
      for (int k = j; k < i; k++) {
        sum_x -= p.l[k] * sin_phi[k];
        sum_y += p.l[k] * cos_phi[k];
      }
      sum_x -= p.c[i] * sin_phi[i];
      sum_y += p.c[i] * cos_phi[i];
      Jvx[i][j] = sum_x;
      Jvy[i][j] = sum_y;
    }
  }

  // Mass matrix M(q)
  for (int j = 0; j < n; j++) {
    for (int k = 0; k < n; k++) {
      double sum = 0;
      int start = (j > k) ? j : k;
      for (int i = start; i < n; i++) {
        sum += p.m[i] * (Jvx[i][j] * Jvx[i][k] + Jvy[i][j] * Jvy[i][k]) + p.I[i];
      }
      M[j][k] = sum;
    }
  }

  // Gravity vector g(q) = dU/dq
  for (int j = 0; j < n; j++) {
    double sum = 0;
    for (int i = j; i < n; i++) {
      sum += p.m[i] * Jvy[i][j];
    }
    g_vec[j] = p.g * sum;
  }

  // Time derivatives of Jacobians: d(Jv)/dt
  // d(sin_phi[k])/dt = cos_phi[k] * d(phi[k])/dt
  // d(cos_phi[k])/dt = -sin_phi[k] * d(phi[k])/dt
  double phi_dot[3];
  phi_dot[0] = v[0];
  for (int i = 1; i < n; i++) phi_dot[i] = phi_dot[i - 1] + v[i];

  double dJvx[3][3] = {};
  double dJvy[3][3] = {};
  for (int i = 0; i < n; i++) {
    for (int j = 0; j <= i; j++) {
      double sum_dx = 0, sum_dy = 0;
      for (int k = j; k < i; k++) {
        sum_dx -= p.l[k] * cos_phi[k] * phi_dot[k];
        sum_dy -= p.l[k] * sin_phi[k] * phi_dot[k];
      }
      sum_dx -= p.c[i] * cos_phi[i] * phi_dot[i];
      sum_dy -= p.c[i] * sin_phi[i] * phi_dot[i];
      dJvx[i][j] = sum_dx;
      dJvy[i][j] = sum_dy;
    }
  }

  // Coriolis and centrifugal vector c(q, v) = sum_i Jv_i^T * m_i * dJv_i * v
  for (int j = 0; j < n; j++) {
    double sum = 0;
    for (int i = j; i < n; i++) {
      double dJv_v_x = 0, dJv_v_y = 0;
      for (int k = 0; k <= i; k++) {
        dJv_v_x += dJvx[i][k] * v[k];
        dJv_v_y += dJvy[i][k] * v[k];
      }
      sum += p.m[i] * (Jvx[i][j] * dJv_v_x + Jvy[i][j] * dJv_v_y);
    }
    c[j] = sum;
  }
}

// Invert symmetric positive-definite M matrix and solve M * a = rhs
int solve_accel(int n, const double M[3][3], const double rhs[3], double out[3]) {
  if (n == 1) {
    if (M[0][0] <= 1e-14) return 2;
    out[0] = rhs[0] / M[0][0];
    return 0;
  }
  if (n == 2) {
    double det = M[0][0] * M[1][1] - M[0][1] * M[0][1];
    if (det <= 1e-14) return 2;
    out[0] = (M[1][1] * rhs[0] - M[0][1] * rhs[1]) / det;
    out[1] = (M[0][0] * rhs[1] - M[0][1] * rhs[0]) / det;
    return 0;
  }
  // n == 3
  double c00 = M[1][1] * M[2][2] - M[1][2] * M[1][2];
  double c01 = -(M[0][1] * M[2][2] - M[1][2] * M[0][2]);
  double c02 = M[0][1] * M[1][2] - M[1][1] * M[0][2];
  double det = M[0][0] * c00 + M[0][1] * c01 + M[0][2] * c02;
  if (det <= 1e-14) return 2;

  double c11 = M[0][0] * M[2][2] - M[0][2] * M[0][2];
  double c12 = -(M[0][0] * M[1][2] - M[0][1] * M[0][2]);
  double c22 = M[0][0] * M[1][1] - M[0][1] * M[0][1];

  out[0] = (c00 * rhs[0] + c01 * rhs[1] + c02 * rhs[2]) / det;
  out[1] = (c01 * rhs[0] + c11 * rhs[1] + c12 * rhs[2]) / det;
  out[2] = (c02 * rhs[0] + c12 * rhs[1] + c22 * rhs[2]) / det;
  return 0;
}

int calc_accel(const TreeParams &p, const double *q, const double *v,
               const double *tau, double *a_out) {
  double M[3][3] = {}, c[3] = {}, g_vec[3] = {}, rhs[3] = {};
  tree_terms(p, q, v, M, c, g_vec);
  for (int i = 0; i < p.n; i++) {
    rhs[i] = tau[i] - c[i] - g_vec[i] - p.b[i] * v[i];
  }
  return solve_accel(p.n, M, rhs, a_out);
}

} // namespace

extern "C" unsigned mini_tree_abi() { return 2; }

extern "C" double *mini_tree_scratch() {
  static double scratch[64];
  return scratch;
}

extern "C" int mini_tree_eval(int op, double *b, unsigned length) {
  if (!b || length != 64 || op < 0 || op > 6) return 1;

  TreeParams p;
  if (!parse_params(b, p)) return 1;

  const double *q = b + 17;
  const double *v = b + 20;
  double t = b[23];

  for (int i = 0; i < p.n; i++) {
    if (!finite(q[i]) || !finite(v[i])) return 1;
  }
  if (!finite(t) || t < 0) return 1;

  double result[16] = {};
  int count = 0;
  int error = 0;

  if (op == 0) { // Terms: M, c, g
    double M[3][3] = {}, c[3] = {}, g_vec[3] = {};
    tree_terms(p, q, v, M, c, g_vec);
    // Unique M elements: M00, M01, M02, M11, M12, M22
    result[0] = M[0][0];
    result[1] = (p.n > 1) ? M[0][1] : 0;
    result[2] = (p.n > 2) ? M[0][2] : 0;
    result[3] = (p.n > 1) ? M[1][1] : 0;
    result[4] = (p.n > 2) ? M[1][2] : 0;
    result[5] = (p.n > 2) ? M[2][2] : 0;
    for (int i = 0; i < 3; i++) {
      result[6 + i] = (i < p.n) ? c[i] : 0;
      result[9 + i] = (i < p.n) ? g_vec[i] : 0;
    }
    count = 12;
  } else if (op == 1) { // Acceleration
    double tau[3] = {b[24], b[25], b[26]};
    for (int i = 0; i < p.n; i++) {
      if (!finite(tau[i])) return 1;
    }
    error = calc_accel(p, q, v, tau, result);
    count = p.n;
  } else if (op == 2 || op == 6) { // RK4 Step or Controlled RK4 Step
    double dt = b[27];
    if (!finite(dt) || dt <= 0 || dt > 1.0 / 120.0) return 1;

    double tau[3] = {b[24], b[25], b[26]};
    double target[3] = {b[28], b[29], b[30]};
    double tau_max = b[31];
    double motors = b[32];

    if (op == 6) {
      if (!finite(tau_max) || tau_max <= 0 || tau_max > 100.0) return 1;
      if (motors != 0.0 && motors != 1.0) return 1;
      for (int i = 0; i < p.n; i++) {
        if (!finite(target[i])) return 1;
      }
    }

    double k_q[4][3] = {}, k_v[4][3] = {};
    double cur_q[3], cur_v[3];

    for (int stage = 0; stage < 4; stage++) {
      double factor = (stage == 3) ? dt : dt / 2.0;
      for (int i = 0; i < p.n; i++) {
        cur_q[i] = q[i] + (stage ? k_q[stage - 1][i] * factor : 0);
        cur_v[i] = v[i] + (stage ? k_v[stage - 1][i] * factor : 0);
        k_q[stage][i] = cur_v[i];
      }

      double stage_tau[3] = {};
      if (op == 6) {
        double M[3][3], c_dummy[3], g_vec[3];
        tree_terms(p, cur_q, cur_v, M, c_dummy, g_vec);
        for (int i = 0; i < p.n; i++) {
          if (motors > 0.5) {
            double u = 24.0 * (target[i] - cur_q[i]) - 5.0 * cur_v[i] + g_vec[i];
            stage_tau[i] = (u < -tau_max) ? -tau_max : (u > tau_max) ? tau_max : u;
          } else {
            stage_tau[i] = 0;
          }
        }
      } else {
        for (int i = 0; i < p.n; i++) stage_tau[i] = tau[i];
      }

      error = calc_accel(p, cur_q, cur_v, stage_tau, k_v[stage]);
      if (error) return error;
    }

    for (int i = 0; i < p.n; i++) {
      result[i] = q[i] + dt * (k_q[0][i] + 2 * k_q[1][i] + 2 * k_q[2][i] + k_q[3][i]) / 6.0;
      result[3 + i] = v[i] + dt * (k_v[0][i] + 2 * k_v[1][i] + 2 * k_v[2][i] + k_v[3][i]) / 6.0;
      if (absval(result[i]) > 1e6 || absval(result[3 + i]) > 1e6) return 3;
    }
    result[6] = t + dt;
    count = 7;

    if (op == 6) {
      // Also return applied control torques at starting state
      double M[3][3], c_dummy[3], g_vec[3];
      tree_terms(p, q, v, M, c_dummy, g_vec);
      for (int i = 0; i < p.n; i++) {
        if (motors > 0.5) {
          double u = 24.0 * (target[i] - q[i]) - 5.0 * v[i] + g_vec[i];
          result[7 + i] = (u < -tau_max) ? -tau_max : (u > tau_max) ? tau_max : u;
        } else {
          result[7 + i] = 0;
        }
      }
      count = 7 + p.n;
    }
  } else if (op == 3) { // Forward Kinematics
    double phi = 0;
    double x = 0, y = 0;
    result[0] = 0; result[1] = 0; // base origin
    for (int i = 0; i < p.n; i++) {
      phi += q[i];
      x += p.l[i] * cos(phi);
      y += p.l[i] * sin(phi);
      result[2 + 2 * i] = x;
      result[3 + 2 * i] = y;
    }
    count = 2 + 2 * p.n;
  } else if (op == 4) { // Energy: K, U, Total
    double M[3][3] = {}, c[3] = {}, g_vec[3] = {};
    tree_terms(p, q, v, M, c, g_vec);

    double K = 0;
    for (int i = 0; i < p.n; i++) {
      for (int j = 0; j < p.n; j++) {
        K += 0.5 * v[i] * M[i][j] * v[j];
      }
    }

    double phi = 0;
    double U = 0;
    double cur_y = 0;
    for (int i = 0; i < p.n; i++) {
      phi += q[i];
      double y_com = cur_y + p.c[i] * sin(phi);
      U += p.m[i] * p.g * y_com;
      cur_y += p.l[i] * sin(phi);
    }

    result[0] = K;
    result[1] = U;
    result[2] = K + U;
    count = 3;
  } else if (op == 5) { // End-effector Jacobian J_ee
    double phi[3];
    phi[0] = q[0];
    for (int i = 1; i < p.n; i++) phi[i] = phi[i - 1] + q[i];

    for (int j = 0; j < p.n; j++) {
      double jx = 0, jy = 0;
      for (int k = j; k < p.n; k++) {
        jx -= p.l[k] * sin(phi[k]);
        jy += p.l[k] * cos(phi[k]);
      }
      result[j] = jx;
      result[3 + j] = jy;
    }
    count = 6;
  }

  if (error) return error;

  for (int j = 0; j < count; j++) {
    if (!finite(result[j])) return 3;
    b[34 + j] = result[j];
  }

  return 0;
}
