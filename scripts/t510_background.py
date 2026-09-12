#!/usr/bin/env python3
"""Explicit reference fit and auto/required/off complex background application.
Input NPZ: visibility[time,pair,bin] (complex), weights[time,bin].
Context JSON binds the selected window to its verified acquisition manifest.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from python.t510_background import fit,save_product

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['fit','apply']);p.add_argument('--input',type=Path,required=True);p.add_argument('--context',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--template',type=Path);p.add_argument('--mode',choices=['auto','required','off'],default='auto');p.add_argument('--valid-for-seconds',type=float,default=300);a=p.parse_args()
 c=json.loads(a.context.read_text())
 with np.load(a.input,allow_pickle=False) as z:v=z['visibility'];w=z['weights']
 m=fit(v,w,c,a.output,valid_for_seconds=a.valid_for_seconds) if a.action=='fit' else save_product(a.output,v,w,c,template=a.template,mode=a.mode)
 print(json.dumps(m))
if __name__=='__main__':main()
