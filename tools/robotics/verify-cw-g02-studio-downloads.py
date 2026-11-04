#!/usr/bin/env python3
"""Independently verify actual Chrome evidence downloads, then native replay."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from seedcore.robotics.cw_evidence import json_bytes
from seedcore.robotics.mujoco_workbench.runtime import require_engine

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();out=args.directory
    report=dict(scope='local_simulation_only',physicalAcceptance=False,executionAuthority='none',cases=[])
    mj=require_engine()
    for label,disposition in [('completed','verified_completed'),('stopped','verified_interrupted')]:
        bundle=out/(label+'.bundle.json');expected=out/(label+'.admission-context.json');trust=out/'trust.json'
        assert json.loads(expected.read_bytes())==json.loads((out/(label+'.expected.json')).read_bytes())
        flags=['--bundle',str(bundle),'--expected',str(expected),'--trust',str(trust)]
        commands={'python':[sys.executable,'-m','seedcore.robotics.cw_evidence'],
                  'rust':[str(ROOT/'rust/target/debug/seedcore-verify'),'verify-cw-evidence']}
        for language,command in commands.items():
            result=subprocess.run(command+flags,cwd=ROOT,capture_output=True,check=False,timeout=15)
            if result.returncode!=0: raise RuntimeError(result.stderr.decode()[:1000])
            actual=json.loads(result.stdout)
            assert actual['disposition']==disposition and actual['physicalAcceptance'] is False
            assert actual==json.loads((out/(label+'.'+language+'.verification.json')).read_bytes())
            (out/(label+'.independent-'+language+'.verification.json')).write_bytes(result.stdout)
        raw=json.loads(bundle.read_bytes())
        source=json.loads(base64.b64decode(raw['artifacts']['source']))
        capture_bytes=base64.b64decode(raw['artifacts']['capture']);capture=json.loads(capture_bytes)
        (out/(label+'.capture.json')).write_bytes(capture_bytes)
        model=mj.MjModel.from_xml_string(source['model']['xml']);data=mj.MjData(model);display=mj.MjData(model)
        for sample in capture['samples']:
            data.ctrl[:]=sample['ctrl'];mj.mj_step(model,data)
            for key,value in [('qpos',data.qpos),('qvel',data.qvel),('qfrcActuator',data.qfrc_actuator),('xpos',data.xpos.reshape(-1))]:
                np.testing.assert_allclose(sample[key],value,atol=1e-12,rtol=0)
            display.qpos[:]=data.qpos;mj.mj_forward(model,display)
            for body,declared in zip(sample['bodies'],source['model']['manifest']['bodies']):
                bid=mj.mj_name2id(model,mj.mjtObj.mjOBJ_BODY,declared['bodyName'])
                np.testing.assert_allclose(body['position_m'],display.xpos[bid],atol=1e-12,rtol=0)
                np.testing.assert_allclose(body['quaternion_wxyz'],display.xquat[bid],atol=1e-12,rtol=0)
        report['cases'].append(dict(label=label,disposition=disposition,samples=len(capture['samples']),nativeTolerance=1e-12))
    report['status']='checks_passed';(out/'independent-verification.json').write_bytes(json_bytes(report))
    print('CW-G02 actual Chrome completed/stopped downloads match both independent CLIs and native MuJoCo replay.')


if __name__=='__main__': main()
