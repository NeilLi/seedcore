#include "mini_physics.h"
#include <cmath>
#include <cassert>
#include <iostream>
void close(double x,double y,double tolerance=1e-8) { assert(std::abs(x-y)<tolerance); }
void init(double *b) { double values[18]={.75,.6,1,.7,9.81,.12,.3,-.9,0,0,0,0,0,1.0/480,.96,-1.22,16,1};for(int i=0;i<18;i++) b[i]=values[i]; }
void advance(double *b,int count,int operation=2) { for(int i=0;i<count;i++) { assert(mini_eval(operation,b,32)==0);for(int j=0;j<5;j++) b[6+j]=b[20+j]; } }
double energy(double *b) { assert(mini_eval(4,b,32)==0);return b[22]; }
int main() {
  double b[32]={};init(b);
  // FK lengths and positive-definite inertia over relative joint angles.
  for(double angle=-3;angle<3;angle+=.02) {
    b[6]=angle;b[7]=angle/2;assert(mini_eval(3,b,32)==0);close(std::hypot(b[20],b[21]),b[0]);close(std::hypot(b[22]-b[20],b[23]-b[21]),b[1]);
    assert(mini_eval(0,b,32)==0);assert(b[20]>0 && b[22]>0 && b[20]*b[22]-b[21]*b[21]>0);
  }
  // Gradient of potential and kinetic/Coriolis identity.
  init(b);b[8]=1.2;b[9]=-.3;assert(mini_eval(0,b,32)==0);
  double g[2]={b[25],b[26]},c[2]={b[23],b[24]},mdot[3],plus[3];
  for(int j=0;j<2;j++) {b[6+j]+=1e-6;mini_eval(4,b,32);double ep=b[21];b[6+j]-=2e-6;mini_eval(4,b,32);double em=b[21];b[6+j]+=1e-6;close((ep-em)/2e-6,g[j],1e-7);}
  b[6]+=1e-6*b[8];b[7]+=1e-6*b[9];mini_eval(0,b,32);for(int j=0;j<3;j++) plus[j]=b[20+j];
  b[6]-=2e-6*b[8];b[7]-=2e-6*b[9];mini_eval(0,b,32);for(int j=0;j<3;j++) mdot[j]=(plus[j]-b[20+j])/2e-6;
  close(b[8]*c[0]+b[9]*c[1],.5*(mdot[0]*b[8]*b[8]+2*mdot[1]*b[8]*b[9]+mdot[2]*b[9]*b[9]));
  // Rest under gravity compensation.
  init(b);mini_eval(0,b,32);b[11]=b[25];b[12]=b[26];advance(b,480);close(b[6],.3);close(b[7],-.9);close(b[8],0);close(b[9],0);
  // Unforced conservation and damping dissipation.
  init(b);b[5]=0;b[8]=.3;b[9]=-.2;b[13]=1.0/960;double start=energy(b);advance(b,1920);close(energy(b),start,1e-5);
  init(b);b[5]=.5;b[8]=.3;b[9]=-.2;start=energy(b);advance(b,960);assert(energy(b)<start);
  // Controlled reach and saturation.
  init(b);advance(b,2880,6);close(b[6],b[14],.01);close(b[7],b[15],.01);close(b[8],0,.01);close(b[9],0,.01);
  init(b);b[16]=2;mini_eval(5,b,32);assert(std::abs(b[20])<=2 && std::abs(b[21])<=2);
  // M a + C + G + damping*v equals effort.
  init(b);b[11]=2;b[12]=-1;mini_eval(1,b,32);double a0=b[20],a1=b[21];mini_eval(0,b,32);close(b[20]*a0+b[21]*a1+b[25],2);close(b[21]*a0+b[22]*a1+b[26],-1);
  // Step refinement.
  double ends[3][4];int counts[3]={120,480,3840};
  for(int i=0;i<3;i++) {init(b);b[5]=0;b[7]=-.1;b[8]=.1;b[9]=.2;b[11]=.2;b[12]=-.1;b[13]=.5/counts[i];advance(b,counts[i]);for(int j=0;j<4;j++) ends[i][j]=b[6+j];}
  double errors[2]={};for(int i=0;i<2;i++) for(int j=0;j<4;j++) errors[i]+=std::pow(ends[i][j]-ends[2][j],2);assert(std::sqrt(errors[1])<std::sqrt(errors[0])/8);
  // Explicit state is complete: exact continuation after copying it.
  init(b);advance(b,1376,6);double resumed[32];for(int j=0;j<32;j++) resumed[j]=b[j];
  advance(b,1504,6);advance(resumed,1504,6);for(int j=6;j<11;j++) assert(b[j]==resumed[j]);
  // Invalid requests never mutate output, including NaN and singular models.
  init(b);b[20]=123;b[13]=0;assert(mini_eval(2,b,32)==1 && b[20]==123);
  init(b);b[11]=NAN;assert(mini_eval(2,b,32)==1);assert(mini_eval(0,b,31)==1);assert(mini_eval(0,nullptr,32)==1);
  init(b);for(int j=0;j<4;j++) b[j]=1e-8;assert(mini_eval(1,b,32)==2);
  std::cout << "12 native invariant groups passed\n";
}
