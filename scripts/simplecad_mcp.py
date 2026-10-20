#!/usr/bin/env python3
"""Run from an MCP client using stdio; FreeCAD runs the opt-in local bridge."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simplecad.mcp.connection import Client
from simplecad.mcp.protocol import serve


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection',help='Private connection file shown in FreeCAD; omit to discover a single running server.')
    args=parser.parse_args()
    if hasattr(sys.stdin,'reconfigure'): sys.stdin.reconfigure(encoding='utf-8')
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    client=Client(args.connection)
    try: serve(sys.stdin,sys.stdout,client.call)
    except (BrokenPipeError,KeyboardInterrupt): pass

if __name__=='__main__': main()
