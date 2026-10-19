import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { RobotAssembly } from '@seedcore/contracts';
import type { Frozen, Selection } from './store.js';
import type { ProxyScene } from './assets.js';

/** Rest-pose proxy preview, isolated from authoring state and execution. */
export class RobotCanvas {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(38, 1, .001, 10);
  private controls: OrbitControls;
  private group = new THREE.Group();
  private observer: ResizeObserver;
  private frame = 0;
  private objects = new Map<string, THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>>();
  private edges = new Map<string, THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>>();
  private origin?: [number,number];
  constructor(private canvas: HTMLCanvasElement, private onSelect: (selection: Selection) => void) {
    this.renderer = new THREE.WebGLRenderer({canvas,antialias:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2)); this.renderer.setClearColor('#e8eeeb');
    this.camera.up.set(0,0,1); this.camera.position.set(.22,-.30,.23);
    this.controls = new OrbitControls(this.camera,canvas); this.controls.target.set(0,0,.035); this.controls.enableDamping = true;
    const grid = new THREE.GridHelper(.5,25,0x9cafa5,0xcbd7cf); grid.rotation.x = Math.PI/2; grid.position.z = -.007; this.scene.add(grid);
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x66776b,3));
    const light = new THREE.DirectionalLight(0xffffff,3); light.position.set(1,-2,3); this.scene.add(light,this.group);
    this.observer = new ResizeObserver(()=>{
      const {width,height} = canvas.getBoundingClientRect(); this.renderer.setSize(width,height,false); this.camera.aspect = width/Math.max(1,height); this.camera.updateProjectionMatrix();
    }); this.observer.observe(canvas);
    canvas.addEventListener('pointerdown',this.down); canvas.addEventListener('pointerup',this.up);
    const render = () => {this.frame = requestAnimationFrame(render); this.controls.update(); this.renderer.render(this.scene,this.camera);}; render();
  }
  private down = (event: PointerEvent) => {this.origin = [event.clientX,event.clientY];};
  private up = (event: PointerEvent) => {
    if (!this.origin || Math.hypot(event.clientX-this.origin[0],event.clientY-this.origin[1])>5) return;
    const rect = this.canvas.getBoundingClientRect(); const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),this.camera);
    const hit = ray.intersectObjects([...this.objects.values()])[0];
    this.onSelect(hit ? {kind:'node',id:hit.object.userData.nodeId} : null);
  };
  setBuild(scene: Frozen<ProxyScene>, assembly: Frozen<RobotAssembly>): void {
    for (const object of [...this.objects.values(),...this.edges.values()]) {object.geometry.dispose(); object.material.dispose();}
    this.group.clear(); this.objects.clear(); this.edges.clear();
    const colors: Record<string,number> = {chassis:0x769886,actuator:0xe3a666,mcu:0x6e9eae,link:0xa7b2c7,bracket:0x93a493};
    for (const node of scene.nodes) {
      const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position',new THREE.Float32BufferAttribute([...node.positions],3)); geometry.setIndex([...node.indices]); geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:colors[node.role]??0xb9b6a5,roughness:.65,side:THREE.DoubleSide}));
      mesh.position.fromArray(node.transform.position_m); const [w,x,y,z] = node.transform.quaternion_wxyz; mesh.quaternion.set(x,y,z,w);
      mesh.userData.nodeId = node.id; this.objects.set(node.id,mesh); this.group.add(mesh);
    }
    for (const edge of assembly.mechanical_tree) {
      const from = this.objects.get(edge.parent_node_id)!.position, to = this.objects.get(edge.child_node_id)!.position;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([from,to]),new THREE.LineBasicMaterial({color:0x8f9f98,depthTest:false,transparent:true,opacity:.6}));
      line.renderOrder=2; this.edges.set(edge.edge_id,line); this.group.add(line);
    }
    this.canvas.dataset.meshState = 'verified'; this.fit();
  }
  select(selection: Frozen<Selection>): void {
    for (const [id,mesh] of this.objects) {mesh.material.emissive.setHex(selection?.kind==='node' && selection.id===id ? 0x255a48 : 0);}
    for (const [id,line] of this.edges) {line.material.color.setHex(selection?.kind==='edge' && selection.id===id ? 0xde681c : 0x8f9f98);}
  }
  fit(): void {
    const box = new THREE.Box3().setFromObject(this.group); if(box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
    const distance = Math.max(.12, size.length())*2.2;
    this.controls.target.copy(center); this.camera.position.copy(center).add(new THREE.Vector3(.7,-1,.8).normalize().multiplyScalar(distance)); this.controls.update();
  }
  dispose(): void {
    cancelAnimationFrame(this.frame); this.observer.disconnect(); this.controls.dispose();
    this.canvas.removeEventListener('pointerdown',this.down); this.canvas.removeEventListener('pointerup',this.up);
    this.scene.traverse(object=>{if(object instanceof THREE.Mesh || object instanceof THREE.Line){object.geometry.dispose();const materials=Array.isArray(object.material)?object.material:[object.material];materials.forEach(m=>m.dispose());}});
    this.renderer.dispose();
  }
}
