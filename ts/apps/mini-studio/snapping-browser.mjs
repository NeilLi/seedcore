import assert from 'node:assert/strict';
import path from 'node:path';

export async function exerciseSnapping(page,output,passed){
  const digest=()=>page.locator('#content-digest').textContent();
  const ghost=()=>page.locator('canvas').getAttribute('data-ghost-state');
  const count=()=>page.locator('#nodes button').count();
  const unchanged=async(expected,n)=>{assert.equal(await digest(),expected);assert.equal(await count(),n);};
  const input=async(id,value)=>{await page.locator(`#${id}`).fill(String(value));};
  await page.waitForFunction(()=>document.querySelector('#catalog-status')?.textContent.includes('12 proxy parts'));
  await page.locator('#placement-tab').focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('#placement-panel').isVisible(),true);
  assert.equal(await page.locator('#part-choice option').count(),12);
  await input('instance-id','cap_02');const before=await digest(),storage=await page.evaluate(()=>localStorage.getItem('seedcore.mini-studio.draft.v2'));
  await page.locator('#stage-placement').focus();await page.keyboard.press('Enter');
  assert.equal(await ghost(),'candidate');assert.equal(await page.locator('#commit-placement').isEnabled(),true);await unchanged(before,5);
  assert.equal(await page.evaluate(()=>localStorage.getItem('seedcore.mini-studio.draft.v2')),storage);
  await page.screenshot({path:path.join(output,'snapping-preview.png'),fullPage:true});
  await page.locator('#clear-placement').click();assert.equal(await ghost(),'none');await unchanged(before,5);
  passed('CW-SNAP-01 keyboard staging and ghost preview do not mutate or persist the draft');
  await page.locator('#stage-placement').click();await input('pose-x',25);assert.equal(await ghost(),'unmatched');assert.equal(await page.locator('#commit-placement').isDisabled(),true);await unchanged(before,5);
  await input('pose-x',15);assert.equal(await ghost(),'candidate');
  await input('pose-w',2);assert.equal(await ghost(),'none');assert.match(await page.locator('#placement-status').textContent(),/unit norm/);
  await input('pose-w',0);await input('pose-qz',1);assert.equal(await ghost(),'unmatched');assert.match(await page.locator('#placement-status').textContent(),/twist/);
  await input('pose-qz',0);await input('pose-x',0);await input('pose-qx',1);assert.equal(await ghost(),'unmatched');assert.match(await page.locator('#placement-status').textContent(),/normal/);
  await input('pose-qx',0);await input('pose-w',1);await input('pose-x',10);await unchanged(before,5);
  passed('CW-SNAP-01 radius, quaternion order/norm, normal and twist rejections retain the accepted draft');
  await page.locator('#commit-placement').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelectorAll('#nodes button').length===6);
  const added=await digest();assert.notEqual(added,before);assert.equal(await ghost(),'none');
  await page.locator('#undo').click();await unchanged(before,5);assert.equal(await ghost(),'none');await page.locator('#redo').click();await unchanged(added,6);
  passed('CW-SNAP-01 keyboard commit adds one rigid mount; undo/redo restore exact content');
  await input('instance-id','cap_02');await page.locator('#stage-placement').click();assert.match(await page.locator('#placement-status').textContent(),/already exists/);await unchanged(added,6);
  await page.locator('#nodes button').filter({hasText:'bracket_0'}).click();await page.locator('#placement-mode').selectOption('move');
  await input('pose-w',0);await input('pose-qx',1);await input('pose-qy',0);await input('pose-qz',0);await input('pose-x',10);await input('pose-y',0);await input('pose-z',-11);
  assert.equal(await ghost(),'candidate');assert.equal(await page.locator('canvas').getAttribute('data-ghost-node-count'),'5');
  await page.locator('#child-port').selectOption('mount.top');assert.match(await page.locator('#placement-status').textContent(),/occupied/);assert.equal(await page.locator('#commit-placement').isDisabled(),true);await page.locator('#child-port').selectOption('mount.bottom');
  const candidates=await page.locator('#snap-candidate option').allTextContents();assert.equal(candidates.length,1);assert.match(candidates[0],/base_0 \/ mount.bottom/);assert.ok(!candidates.some(c=>/bracket_0|servo_0|hat_0|mcu_0|cap_02/.test(c)));await unchanged(added,6);
  // A stale/invalid dropdown value cannot leave the previous candidate armed.
  await page.locator('#snap-candidate').evaluate(select=>{select.add(new Option('invalid subtree target','999'));select.value='999';select.dispatchEvent(new Event('change',{bubbles:true}));});
  assert.equal(await page.locator('#commit-placement').isDisabled(),true);await unchanged(added,6);
  await page.locator('#preview-placement').click();assert.equal(await ghost(),'candidate');await page.screenshot({path:path.join(output,'subtree-preview.png'),fullPage:true});
  await page.locator('#commit-placement').click();await page.waitForFunction(expected=>document.querySelector('#content-digest').textContent!==expected,added);
  const moved=await digest(),saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('seedcore.mini-studio.draft.v2')));
  assert.equal(saved.mechanical_tree.find(edge=>edge.child_node_id==='bracket_0').parent_port_id,'mount.bottom');assert.equal(saved.mechanical_tree.filter(edge=>edge.connection_type==='articulated_joint').length,1);
  await page.locator('#undo').click();await unchanged(added,6);await page.locator('#redo').click();await unchanged(moved,6);
  passed('CW-SNAP-01 rotated subtree reparent, cycle-target exclusion and undo/redo preserve explicit joints');
  // Root movement is not a supported operation, and cannot change the graph.
  await page.locator('#nodes button').filter({hasText:'base_0'}).click();await page.locator('#stage-placement').click();assert.match(await page.locator('#placement-status').textContent(),/root/);assert.equal(await page.locator('#commit-placement').isDisabled(),true);await unchanged(moved,6);
  await page.locator('#placement-mode').selectOption('new');await input('instance-id','denied_cap');await page.locator('#stage-placement').click();
  await page.route('**/api/assembly/validate',route=>route.fulfill({status:422,contentType:'application/json',body:'{"detail":"synthetic placement refusal"}'}));
  await page.locator('#commit-placement').click();await page.waitForFunction(()=>document.querySelector('#status').dataset.error==='true');await unchanged(moved,6);assert.equal(await ghost(),'none');await page.unroute('**/api/assembly/validate');
  passed('CW-SNAP-01 root and authoritative drop rejection retain the prior revision');
  await input('instance-id','drag_cap');await page.locator('#stage-placement').click();assert.equal(await ghost(),'candidate');
  const rect=await page.locator('canvas').boundingBox();await page.keyboard.down('Shift');await page.mouse.move(rect.x+rect.width*.5,rect.y+rect.height*.5);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.5+2,rect.y+rect.height*.5+1);
  await unchanged(moved,6);assert.equal(await ghost(),'candidate');await page.mouse.up();await page.keyboard.up('Shift');await page.waitForFunction(()=>document.querySelectorAll('#nodes button').length===7);assert.equal(await ghost(),'none');
  passed('CW-SNAP-01 Shift-drag previews without mutation and commits atomically on release');
  await page.screenshot({path:path.join(output,'snapping-final.png'),fullPage:true});
}
