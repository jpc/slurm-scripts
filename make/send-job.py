#!/usr/bin/env python3
import requests, sys, os
ret = requests.post('http://localhost:4444', json={'argv':sys.argv[2:], 'cwd':os.getcwd(), 'env':dict(os.environ)})
ret.raise_for_status()
sys.exit(ret.json()['rc'])
