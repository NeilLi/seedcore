import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { RobotAssembly } from '@seedcore/contracts';
import type { Frozen, Selection } from './store.js';
import type { ProxyScene,ProxyNode } from './assets.js';
import type {RelativeTransform} from '@seedcore/contracts';

export interface PlacementDrag {
  pose:RelativeTransform;
  onPose:(pose:RelativeTransform)=>void;
  onDrop:()=>void;
}

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
  private ghosts=new THREE.Group();
  private placementDrag?:PlacementDrag;
  private dragging?:{plane:THREE.Plane;offset:THREE.Vector3};
  constructor(private canvas: HTMLCanvasElement, private onSelect: (selection: Selection) => void) {
    this.renderer = new THREE.WebGLRenderer({canvas,antialias:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2)); this.renderer.setClearColor('#e8eeeb');
    this.camera.up.set(0,0,1); this.camera.position.set(.22,-.30,.23);
    this.controls = new OrbitControls(this.camera,canvas); this.controls.target.set(0,0,.035); this.controls.enableDamping = true;
    const grid = new THREE.GridHelper(.5,25,0x9cafa5,0xcbd7cf); grid.rotation.x = Math.PI/2; grid.position.z = -.007; this.scene.add(grid);
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x66776b,3));
    const light = new THREE.DirectionalLight(0xffffff,3); light.position.set(1,-2,3); this.scene.add(light,this.group,this.ghosts);
    this.observer = new ResizeObserver(()=>{
      const {width,height} = canvas.getBoundingClientRect(); this.renderer.setSize(width,height,false); this.camera.aspect = width/Math.max(1,height); this.camera.updateProjectionMatrix();
    }); this.observer.observe(canvas);
    canvas.addEventListener('pointerdown',this.down,true);canvas.addEventListener('pointermove',this.move,true);canvas.addEventListener('pointerup',this.up,true);canvas.addEventListener('pointercancel',this.cancelDrag,true);canvas.addEventListener('lostpointercapture',this.cancelDrag);
    const render = () => {this.frame = requestAnimationFrame(render); this.controls.update(); this.renderer.render(this.scene,this.camera);}; render();
  }
  private ray(event:PointerEvent):THREE.Raycaster {
    const rect=this.canvas.getBoundingClientRect(),ray=new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),this.camera);return ray;
  }
  private down=(event:PointerEvent)=>{
    if(event.button===0&&event.shiftKey&&this.placementDrag){
      const position=new THREE.Vector3().fromArray(this.placementDrag.pose.position_m),plane=new THREE.Plane(new THREE.Vector3(0,0,1),-position.z),point=new THREE.Vector3();
      if(this.ray(event).ray.intersectPlane(plane,point)){this.dragging={plane,offset:position.sub(point)};this.controls.enabled=false;this.canvas.setPointerCapture(event.pointerId);event.preventDefault();event.stopPropagation();this.origin=undefined;return;}
    }
    this.origin=[event.clientX,event.clientY];
  };
  private move=(event:PointerEvent)=>{
    if(!this.dragging||!this.placementDrag)return;const point=new THREE.Vector3();
    if(this.ray(event).ray.intersectPlane(this.dragging.plane,point)){point.add(this.dragging.offset);this.placementDrag.onPose({position_m:point.toArray(),quaternion_wxyz:[...this.placementDrag.pose.quaternion_wxyz]});}
    event.preventDefault();event.stopPropagation();
  };
  private cancelDrag=()=>{this.dragging=undefined;this.controls.enabled=true;};
  private up=(event:PointerEvent)=>{
    if(this.dragging){const handler=this.placementDrag;this.cancelDrag();if(this.canvas.hasPointerCapture(event.pointerId))this.canvas.releasePointerCapture(event.pointerId);event.preventDefault();event.stopPropagation();handler?.onDrop();return;}
    if(!this.origin||Math.hypot(event.clientX-this.origin[0],event.clientY-this.origin[1])>5)return;
    const hit=this.ray(event).intersectObjects([...this.objects.values()])[0];this.origin=undefined;
    this.onSelect(hit?{kind:'node',id:hit.object.userData.nodeId}:null);
  };
  setPlacementDrag(handler:PlacementDrag|undefined):void {this.placementDrag=handler;if(!handler)this.cancelDrag();}
  setGhost(nodes:Frozen<ProxyNode[]>|null,valid=true):void {
    for(const object of [...this.ghosts.children])if(object instanceof THREE.Mesh){object.geometry.dispose();object.material.dispose();}
    this.ghosts.clear();
    for(const node of nodes??[]){const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute([...node.positions],3));geometry.setIndex([...node.indices]);geometry.computeVertexNormals();
      const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:valid?0x22a376:0xc86443,transparent:true,opacity:.35,depthWrite:false,depthTest:false,side:THREE.DoubleSide}));
      mesh.position.fromArray(node.transform.position_m);const [w,x,y,z]=node.transform.quaternion_wxyz;mesh.quaternion.set(x,y,z,w);mesh.renderOrder=5;this.ghosts.add(mesh);
    }
    this.canvas.dataset.ghostState=nodes?.length?(valid?'candidate':'unmatched'):'none';this.canvas.dataset.ghostNodeCount=String(nodes?.length??0);
  }
  setBuild(scene: Frozen<ProxyScene>, assembly: Frozen<RobotAssembly>): void {
    this.setGhost(null);this.setPlacementDrag(undefined);
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
    this.camera.far=Math.max(10,distance*4);this.camera.updateProjectionMatrix();
    this.controls.target.copy(center); this.camera.position.copy(center).add(new THREE.Vector3(.7,-1,.8).normalize().multiplyScalar(distance)); this.controls.update();
  }
  dispose(): void {
    cancelAnimationFrame(this.frame); this.observer.disconnect(); this.controls.dispose();
    this.canvas.removeEventListener('pointerdown',this.down,true);this.canvas.removeEventListener('pointermove',this.move,true);this.canvas.removeEventListener('pointerup',this.up,true);this.canvas.removeEventListener('pointercancel',this.cancelDrag,true);this.canvas.removeEventListener('lostpointercapture',this.cancelDrag);
    this.scene.traverse(object=>{if(object instanceof THREE.Mesh || object instanceof THREE.Line){object.geometry.dispose();const materials=Array.isArray(object.material)?object.material:[object.material];materials.forEach(m=>m.dispose());}});
    this.renderer.dispose();
  }
}
