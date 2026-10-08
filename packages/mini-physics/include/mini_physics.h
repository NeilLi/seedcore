#ifndef SEEDCORE_MINI_PHYSICS_H
#define SEEDCORE_MINI_PHYSICS_H
#ifdef __cplusplus
extern "C" {
#endif
/* ABI 1, no allocation, exceptions or retained pointers. Caller owns 32 doubles.
 * Input: [l1,l2,m1,m2,gravity,damping,q1,q2,v1,v2,time,u1,u2,dt,target1,target2,limit,motors].
 * Output at 20: terms(7), acceleration(2), step(5), forward(4), energy(3), motor(2), controlled_step(5). Operations are 0..6 in this order.
 * Return 0 OK, 1 invalid length/input/op, 2 singular inertia, 3 divergence.
 * On failure output remains unchanged. Unused input fields need not be initialized.
 */
int mini_eval(int operation, double *buffer, unsigned length);
double *mini_scratch(void); /* Wasm adapter's dedicated 32-double scratch only. */
unsigned mini_abi(void);
#ifdef __cplusplus
}
#endif
#endif
