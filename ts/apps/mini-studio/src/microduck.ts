import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';

declare const __MICRODUCK_DEMO__: {
  asset:{uri:string;sha256:string;bytes:number}; meshCount:number; bodyCount:number; visualCount:number;
  source:{revision:string;repository_url:string;license:string};
};

/** Original visual model only. Pose controls never enter assembly, physics or admission. */
export function setupMicroduck(): () => void {
  const canvas = document.getElementById('demo-viewport') as HTMLCanvasElement;
  const status = document.getElementById('demo-status')!;
  const fields = document.getElementById('demo-pose') as HTMLFieldSetElement;
  const controller = new AbortController();
  let renderer:THREE.WebGLRenderer|undefined, controls:OrbitControls|undefined, observer:ResizeObserver|undefined;
  let model:THREE.Group|undefined, frame=0, disposed=false;
  const joints = new Map<string,{object:THREE.Object3D;rest:THREE.Quaternion;axis:THREE.Vector3;range:number[]}>();
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(35,1,.001,10);
  const release = (object:THREE.Object3D) => {
    const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>();
    object.traverse(child=>{if(child instanceof THREE.Mesh){geometries.add(child.geometry);for(const material of Array.isArray(child.material)?child.material:[child.material])materials.add(material);}});
    geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());
  };
  const fit = (direction=new THREE.Vector3(1,-1,.55)) => {
    if(!model||!controls)return;
    const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
    const fov=Math.min(THREE.MathUtils.degToRad(camera.fov),2*Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov)/2)*camera.aspect));
    const distance=size.length()/2/Math.sin(fov/2)*1.16;
    controls.target.copy(center);camera.position.copy(center).add(direction.normalize().multiplyScalar(distance));controls.update();
  };
  const inputs=[...document.querySelectorAll<HTMLInputElement>('[data-demo-joint]')];
  for(const input of inputs)input.oninput=()=>{
    const joint=joints.get(input.dataset.demoJoint!);if(!joint)return;
    const degrees=Number(input.value),angle=THREE.MathUtils.degToRad(degrees);
    if(!Number.isFinite(angle)||angle<joint.range[0]||angle>joint.range[1])return;
    joint.object.quaternion.copy(joint.rest).multiply(new THREE.Quaternion().setFromAxisAngle(joint.axis,angle));
    document.getElementById(`${input.id}-value`)!.textContent=`${degrees}°`;
    canvas.dataset.poseState='posed';
  };
  document.getElementById('demo-reset')!.onclick=()=>{
    for(const joint of joints.values())joint.object.quaternion.copy(joint.rest);
    inputs.forEach(input=>{input.value='0';document.getElementById(`${input.id}-value`)!.textContent='0°';});
    canvas.dataset.poseState='rest';fit();
  };
  for(const button of document.querySelectorAll<HTMLButtonElement>('[data-demo-view]'))button.onclick=()=>{
    const view=button.dataset.demoView;
    fit(view==='front'?new THREE.Vector3(1,0,.15):view==='side'?new THREE.Vector3(0,-1,.15):new THREE.Vector3(1,-1,.55));
  };
  const load = async () => {
    try {
      renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor('#e8eeeb');
      camera.up.set(0,0,1);
      controls=new OrbitControls(camera,canvas);controls.enableDamping=true;
      scene.add(new THREE.HemisphereLight(0xffffff,0x778979,2.5));
      const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(1,-2,3);scene.add(key);
      const fill=new THREE.DirectionalLight(0xffffff,1);fill.position.set(-1,2,1);scene.add(fill);
      observer=new ResizeObserver(()=>{const {width,height}=canvas.getBoundingClientRect();if(!width||!height)return;renderer?.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();fit();});observer.observe(canvas);
      const response=await fetch(`/${__MICRODUCK_DEMO__.asset.uri}`,{signal:controller.signal});
      if(!response.ok)throw new Error('The local robot model could not be loaded.');
      const bytes=await response.arrayBuffer();
      const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
      if(bytes.byteLength!==__MICRODUCK_DEMO__.asset.bytes||digest!==__MICRODUCK_DEMO__.asset.sha256)throw new Error('The robot model failed its integrity check.');
      if(disposed)return;
      const gltf=await new GLTFLoader().parseAsync(bytes,'');
      if(disposed){release(gltf.scene);return;}
      model=gltf.scene;
      // glTF uses Y-up; the workshop uses the source MJCF Z-up convention.
      model.rotation.x=Math.PI/2;
      model.traverse(object=>{
        const joint=object.userData.joint;
        if(joint)joints.set(joint.name,{object,rest:object.quaternion.clone(),axis:new THREE.Vector3().fromArray(joint.axis).normalize(),range:joint.range});
      });
      scene.add(model);model.updateMatrixWorld(true);
      const box=new THREE.Box3().setFromObject(model);
      const grid=new THREE.GridHelper(.5,20,0xa6b8aa,0xd2ddd4);grid.rotation.x=Math.PI/2;grid.position.z=box.min.z-.001;scene.add(grid);
      fit();fields.disabled=false;
      canvas.dataset.meshState='verified';canvas.dataset.poseState='rest';canvas.dataset.jointCount=String(joints.size);
      canvas.dataset.visualCount=String(__MICRODUCK_DEMO__.visualCount);
      status.textContent=`Complete Microduck model · ${__MICRODUCK_DEMO__.meshCount} original mesh files · ${joints.size} movable joints. Drag the robot to look around.`;
      document.getElementById('demo-source')!.textContent=`Pollen Robotics · ${__MICRODUCK_DEMO__.source.license} · source ${__MICRODUCK_DEMO__.source.revision.slice(0,12)}`;
      const draw=()=>{if(disposed)return;frame=requestAnimationFrame(draw);controls?.update();renderer?.render(scene,camera);};draw();
    } catch(error) {
      if(disposed)return;
      canvas.dataset.meshState='failed';status.textContent=`${error instanceof Error?error.message:'3D preview unavailable.'} You can still open a project or start the practice lesson.`;
      status.setAttribute('role','alert');
    }
  };
  void load();
  return ()=>{disposed=true;controller.abort();cancelAnimationFrame(frame);observer?.disconnect();controls?.dispose();release(scene);renderer?.dispose();};
}
