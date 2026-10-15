/* Read-only original proxy viewer. No robot controls, signing keys or port access. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const canvas = $('viewport'), ctx = canvas.getContext('2d');
  let parts = [], selected = null, vertices = [], indices = [], epoch = 0;
  let yaw = -.65, pitch = .5, zoom = 1, drag = null;
  const service = (text, error = false) => { $('service').textContent = text; $('service').className = error ? 'error' : ''; };
  const icons = {mcu:'▤',actuator:'◈',sensor:'◎',power:'ϟ',chassis:'▱'};

  function palette() {
    const query = $('search').value.toLowerCase(), category = $('category').value;
    const visible = parts.filter(p => (category === 'all' || p.identity.category === category) &&
      `${p.identity.name} ${p.identity.part_id}`.toLowerCase().includes(query));
    $('parts').replaceChildren(); $('count').textContent = `${visible.length} / ${parts.length}`;
    for (const part of visible) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'part';
      button.dataset.partId = part.identity.part_id; button.setAttribute('aria-pressed', String(selected === part));
      const icon = document.createElement('span'); icon.className = 'part-icon'; icon.textContent = icons[part.identity.category];
      const label = document.createElement('span'), title = document.createElement('strong'), hint = document.createElement('small');
      title.textContent = part.identity.name.replace(' - illustrative draft',''); hint.textContent = `${part.identity.category} · draft`;
      label.append(title,hint); button.append(icon,label); button.addEventListener('click', () => select(part)); $('parts').append(button);
    }
    if (!visible.length) { const empty = document.createElement('p'); empty.textContent = 'No matching parts.'; $('parts').append(empty); }
  }

  async function mesh(part) {
    const response = await fetch(`/${part.mechanical.visual_mesh.uri}`);
    if (!response.ok) throw new Error('Part mesh is unavailable.');
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 1048576) throw new Error('Part mesh exceeds the viewer limit.');
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    if (hash !== part.mechanical.visual_mesh.sha256) throw new Error('Part mesh integrity check failed.');
    const view = new DataView(bytes);
    if (view.getUint32(0,true)!==0x46546c67 || view.getUint32(4,true)!==2 || view.getUint32(8,true)!==bytes.byteLength) throw new Error('Unsupported GLB header.');
    const length = view.getUint32(12,true), binHeader = 20+length;
    if (view.getUint32(16,true)!==0x4e4f534a || view.getUint32(binHeader+4,true)!==0x004e4942) throw new Error('Unsupported GLB chunks.');
    const model = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes,20,length)));
    if (part.mechanical.visual_mesh.origin!=='seedcore_box_proxy' || model.accessors[0].count!==8 || model.accessors[1].count!==36) throw new Error('This Phase 1 viewer supports original box proxies only.');
    const positions = new Float32Array(bytes,binHeader+8+model.bufferViews[0].byteOffset,24);
    // glTF Y-up -> part Z-up. Snap frames use [w,x,y,z] in this part frame.
    const points = Array.from({length:8},(_,i)=>[positions[i*3],-positions[i*3+2],positions[i*3+1]]);
    const faces = [...new Uint16Array(bytes,binHeader+8+model.bufferViews[1].byteOffset,36)];
    if (points.flat().some(v=>!Number.isFinite(v)) || faces.some(v=>v>=8)) throw new Error('Invalid proxy geometry.');
    return [points,faces];
  }

  async function select(part) {
    const request = ++epoch; selected = part; vertices = []; indices = []; palette();
    canvas.dataset.meshState = 'loading'; canvas.dataset.partId = part.identity.part_id;
    service('Checking selected part geometry…');
    $('part-name').textContent = part.identity.name.replace(' - illustrative draft','');
    $('part-id').textContent = part.identity.part_id; $('version').textContent = part.identity.version;
    $('dimensions').textContent = part.mechanical.collision.size_m.map(v=>`${(v*1000).toFixed(0)} mm`).join(' × ');
    $('mass').textContent = `${(part.mechanical.mass_kg*1000).toFixed(1)} g · simulation assumption`;
    $('cost').textContent = part.identity.bom_cost_usd===null ? 'Unknown · no quote' : `$${part.identity.bom_cost_usd} · ${part.identity.cost_basis}`;
    $('electrical').textContent = part.electrical.rating_basis==='not_applicable' ? 'Not applicable' : 'Unknown · no wiring approval';
    $('interfaces').textContent = [...new Set(part.electrical.bus_interfaces.map(b=>b.kind))].join(', ') || 'None selected';
    $('capabilities').textContent = part.hal_and_safety.capabilities.join(', ') || 'Passive component';
    $('record').textContent = JSON.stringify(part,null,2); $('ports').replaceChildren();
    for (const port of part.mechanical.snap_ports) {
      const row=document.createElement('div'); row.className='port'; const name=document.createElement('strong'), detail=document.createElement('code');
      name.textContent=`${port.port_id} · illustrative mount`;
      detail.textContent=`xyz [${port.position_m.join(', ')}] m · wxyz [${port.quaternion_wxyz.join(', ')}]`;
      row.append(name,detail); $('ports').append(row);
    }
    draw();
    try {
      const loaded = await mesh(part); if (request!==epoch) return;
      [vertices,indices]=loaded; canvas.dataset.meshState = 'verified'; draw(); service(`${parts.length} draft parts · geometry hashes checked · hardware qualification open`);
    } catch (error) { if(request===epoch) { canvas.dataset.meshState = 'error'; service(error.message,true); } }
  }

  function rotate(q,v) {
    const [w,x,y,z]=q, [a,b,c]=v;
    const tx=2*(y*c-z*b), ty=2*(z*a-x*c), tz=2*(x*b-y*a);
    return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];
  }

  function draw() {
    const rect=canvas.getBoundingClientRect(), dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(rect.width*dpr); canvas.height=Math.round(rect.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
    const width=rect.width,height=rect.height;ctx.clearRect(0,0,width,height);
    if(!selected) return;
    const size=selected.mechanical.collision.size_m, span=Math.max(...size), scale=Math.min(width,height)*.65/span*zoom;
    function project([x,y,z]) {
      const a=x*Math.cos(yaw)-y*Math.sin(yaw), b=x*Math.sin(yaw)+y*Math.cos(yaw);
      const up=z*Math.cos(pitch)-b*Math.sin(pitch), depth=z*Math.sin(pitch)+b*Math.cos(pitch);
      const perspective=1/(1+depth/(span*5));return [width/2+a*scale*perspective,height*.53-up*scale*perspective,depth];
    }
    function line(a,b,color,width=1) {const p=project(a),q=project(b);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();}
    const floor=-size[2]/2, reach=Math.ceil(span*1.2/.01)*.01;
    for(let n=-reach;n<=reach+.00001;n+=.01){line([n,-reach,floor],[n,reach,floor],'#dce5d6');line([-reach,n,floor],[reach,n,floor],'#dce5d6');}
    const faces=[];
    for(let i=0;i<indices.length;i+=3){const points=indices.slice(i,i+3).map(j=>project(vertices[j]));faces.push({points,depth:points.reduce((a,p)=>a+p[2],0)/3,index:i});}
    faces.sort((a,b)=>b.depth-a.depth);
    for(const face of faces){ctx.beginPath();face.points.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=['#c2d5b5','#abc4a1','#e0e9d7'][Math.floor(face.index/6)%3];ctx.fill();ctx.strokeStyle='#587c67';ctx.lineWidth=1;ctx.stroke();}
    for(const port of selected.mechanical.snap_ports){const p=project(port.position_m),normal=rotate(port.quaternion_wxyz,[0,0,span*.3]);const end=port.position_m.map((v,i)=>v+normal[i]);line(port.position_m,end,'#176a58',2);ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.fillStyle='#176a58';ctx.fill();ctx.fillStyle='#183f38';ctx.font='11px system-ui';ctx.fillText(port.port_id,p[0]+9,p[1]-8);}
  }

  $('search').addEventListener('input',palette);$('category').addEventListener('change',palette);
  $('reset').addEventListener('click',()=>{yaw=-.65;pitch=.5;zoom=1;draw();});
  canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag[0])*.01;pitch=Math.max(-1.2,Math.min(1.2,pitch+(e.clientY-drag[1])*.01));drag=[e.clientX,e.clientY];draw();});
  for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(2,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
  canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')yaw-=.1;else if(e.key==='ArrowRight')yaw+=.1;else if(e.key==='ArrowUp')pitch=Math.min(1.2,pitch+.1);else if(e.key==='ArrowDown')pitch=Math.max(-1.2,pitch-.1);else zoom=Math.max(.4,Math.min(2,zoom*(e.key==='-'?.9:1.1)));draw();});
  new ResizeObserver(draw).observe(canvas);
  fetch('/api/catalog').then(async response=>{if(!response.ok)throw new Error('Catalog validation failed.');return response.json();})
    .then(data=>{if(data.scope!=='authoring_only')throw new Error('Unexpected catalog scope.');parts=data.parts;$('reference-state').textContent='Pinned native package integrity checked';return select(parts[0]);})
    .catch(error=>service(error.message,true));
})();
