#include "mini_physics.h"
#include <iostream>
#include <iomanip>
int main(int argc,char **) {
  std::cout << std::setprecision(17);
  int op; double b[32]={};
  while(std::cin >> op) {
    for(int i=0;i<18;i++) if(!(std::cin >> b[i])) return 1;
    if(argc>1) {
      for(int tick=0;tick<2880;tick++) {
        const int status=mini_eval(6,b,32);std::cout << status;
        for(int i=20;i<25;i++) std::cout << ' ' << b[i];std::cout << '\n';
        if(status) return status;
        for(int i=0;i<5;i++) b[6+i]=b[20+i];
      }
      return 0;
    }
    const int status=mini_eval(op,b,32); std::cout << status;
    for(int i=20;i<27;i++) std::cout << ' ' << b[i];
    std::cout << '\n';
  }
}
