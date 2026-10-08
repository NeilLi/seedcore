#include "mini_physics.h"
#ifdef __wasm__
extern "C" double sin(double);
extern "C" double cos(double);
#else
#include <cmath>
using std::sin; using std::cos;
#endif
namespace {
bool finite(double x) { return __builtin_isfinite(x); }
double absval(double x) { return x < 0 ? -x : x; }
void terms(const double *m, const double *s, double *out) {
  const double c1=m[0]/2, c2=m[1]/2;
  const double i1=m[2]*m[0]*m[0]/12, i2=m[3]*m[1]*m[1]/12;
  const double b=m[3]*m[0]*c2, d=i2+m[3]*c2*c2;
  const double a=i1+m[2]*c1*c1+m[3]*m[0]*m[0]+d;
  const double h=b*sin(s[1]), common=m[3]*c2*m[4]*cos(s[0]+s[1]);
  out[0]=a+2*b*cos(s[1]); out[1]=d+b*cos(s[1]); out[2]=d;
  out[3]=-h*(2*s[2]*s[3]+s[3]*s[3]); out[4]=h*s[2]*s[2];
  out[5]=(m[2]*c1+m[3]*m[0])*m[4]*cos(s[0])+common; out[6]=common;
}
int acceleration(const double *m,const double *s,const double *u,double *out) {
  double t[7]; terms(m,s,t);
  const double det=t[0]*t[2]-t[1]*t[1]; if (!(det>1e-14)) return 2;
  const double r0=u[0]-t[3]-t[5]-m[5]*s[2], r1=u[1]-t[4]-t[6]-m[5]*s[3];
  out[0]=(t[2]*r0-t[1]*r1)/det; out[1]=(t[0]*r1-t[1]*r0)/det;
  return 0;
}
}
extern "C" unsigned mini_abi() { return 1; }
extern "C" double *mini_scratch() { static double scratch[32]; return scratch; }
extern "C" int mini_eval(int op,double *b,unsigned length) {
  if (!b || length!=32 || op<0 || op>6) return 1;
  for (int i=0;i<11;i++) if (!finite(b[i])) return 1;
  for (int i=0;i<4;i++) if (!(b[i]>0 && b[i]<=10)) return 1;
  if (b[4]<0 || b[4]>100 || b[5]<0 || b[5]>100 || b[10]<0) return 1;
  double result[7]={}; const double *s=b+6; int count=0, error=0;
  if (op==0) { terms(b,s,result); count=7; }
  if (op==1 || op==2 || op==6) {
    if (!finite(b[11]) || !finite(b[12])) return 1;
    if (op==1) { error=acceleration(b,s,b+11,result); count=2; }
    else {
      if (op==6 && (!finite(b[14]) || !finite(b[15]) || !finite(b[16]) || b[16]<=0 || b[16]>100 || (b[17]!=0 && b[17]!=1))) return 1;
      const double dt=b[13]; if (!finite(dt) || dt<=0 || dt>1.0/120) return 1;
      double k[4][4], y[4];
      for (int stage=0;stage<4;stage++) {
        const double factor=stage==3 ? dt : dt/2;
        for (int j=0;j<4;j++) y[j]=s[j]+(stage ? k[stage-1][j]*factor : 0);
        k[stage][0]=y[2]; k[stage][1]=y[3];
        double u[2]={b[11],b[12]};
        if (op==6) {
          double t[7]; terms(b,y,t);
          for(int j=0;j<2;j++) {
            const double command=24*(b[14+j]-y[j])-5*y[2+j]+t[5+j];
            u[j]=b[17] ? (command < -b[16] ? -b[16] : command > b[16] ? b[16] : command) : 0;
          }
        }
        error=acceleration(b,y,u,k[stage]+2); if (error) return error;
      }
      for(int j=0;j<4;j++) result[j]=s[j]+dt*(k[0][j]+2*k[1][j]+2*k[2][j]+k[3][j])/6;
      result[4]=b[10]+dt; count=5;
      for(int j=0;j<4;j++) if (absval(result[j])>1e6) return 3;
    }
  }
  if (op==3) {
    result[0]=b[0]*cos(s[0]); result[1]=b[0]*sin(s[0]);
    result[2]=result[0]+b[1]*cos(s[0]+s[1]); result[3]=result[1]+b[1]*sin(s[0]+s[1]); count=4;
  }
  if (op==4) {
    double t[7]; terms(b,s,t);
    result[0]=(t[0]*s[2]*s[2]+2*t[1]*s[2]*s[3]+t[2]*s[3]*s[3])/2;
    result[1]=b[4]*((b[2]*b[0]/2+b[3]*b[0])*sin(s[0])+b[3]*b[1]/2*sin(s[0]+s[1]));
    result[2]=result[0]+result[1]; count=3;
  }
  if (op==5) {
    if (!finite(b[14]) || !finite(b[15]) || !finite(b[16]) || b[16]<=0 || b[16]>100) return 1;
    double t[7]; terms(b,s,t);
    for(int j=0;j<2;j++) { double u=24*(b[14+j]-s[j])-5*s[2+j]+t[5+j]; result[j]=u < -b[16] ? -b[16] : u > b[16] ? b[16] : u; }
    count=2;
  }
  if(error) return error;
  for(int j=0;j<count;j++) if(!finite(result[j])) return 3;
  for(int j=0;j<count;j++) b[20+j]=result[j];
  return 0;
}
