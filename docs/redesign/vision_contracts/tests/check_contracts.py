#!/usr/bin/env python3
"""Local OpenAPI composition/conformance checks, optionally against real opal_kernel.yaml.

Default mode uses a verified upstream component-name manifest when the original
OPAL kernel file is absent. That mode is NOT a full external-ref bundle check.
--strict requires the real kernel file and fully resolves external references.
"""
from pathlib import Path
import argparse
import json
import re
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]
OPENAPI=ROOT/'openapi'
MANIFEST=json.loads((ROOT/'tests'/'opal_kernel_manifest.json').read_text())
KERNEL=OPENAPI/'shared'/'opal_kernel.yaml'
SPECS=[OPENAPI/'shared'/'vision_kernel.yaml']+[OPENAPI/'engines'/f'{n}.yaml' for n in ['yolo','rfdetr','rtdetr','dfine']]
METHODS={'get','post','put','patch','delete','head','options','trace'}

class ContractIssue(Exception):pass

def resolve_pointer(data, pointer, context):
    if not pointer.startswith('/'):raise ContractIssue(f'{context}: malformed JSON pointer #{pointer}')
    obj=data
    for segment in pointer[1:].split('/'):
        k=segment.replace('~1','/').replace('~0','~')
        try:obj=obj[int(k)] if isinstance(obj,list) else obj[k]
        except (KeyError,IndexError,ValueError,TypeError) as e:raise ContractIssue(f'{context}: unresolved pointer #{pointer} segment {k!r}') from e
    return obj

class Resolver:
    def __init__(self, strict=False):
        self.strict=strict
        self.cache={}
        self.known_kernel_manifest_refs=0
        self.full_kernel_refs=0
    def load(self,path):
        path=Path(path).resolve()
        if path not in self.cache:
            if not path.exists():raise ContractIssue(f'Missing file {path}')
            data=yaml.safe_load(path.read_text())
            if not isinstance(data,dict):raise ContractIssue(f'Not YAML mapping {path}')
            self.cache[path]=data
        return self.cache[path]
    def resolve(self, origin,ref):
        if not isinstance(ref,str):raise ContractIssue(f'{origin}: $ref must be string')
        f,hashmark,ptr=ref.partition('#')
        target=(origin.parent / f).resolve() if f else origin.resolve()
        if not hashmark:raise ContractIssue(f'{origin}: missing # pointer {ref}')
        if target==KERNEL.resolve() and not target.exists():
            if self.strict:raise ContractIssue('Strict requires real openapi/shared/opal_kernel.yaml')
            parts=ptr.lstrip('/').split('/')
            if len(parts)!=3 or parts[0]!='components' or parts[2] not in MANIFEST['components'].get(parts[1],[]):
                raise ContractIssue(f'{origin}: kernel symbol not in pinned upstream manifest: {ref}')
            self.known_kernel_manifest_refs+=1
            return {'_manifest_only':True},target
        doc=self.load(target)
        if target==KERNEL.resolve():self.full_kernel_refs+=1
        return resolve_pointer(doc,ptr,f'{origin}: {ref}'),target

def collect_refs(node,origin,resolver,seen=None):
    if seen is None:seen=set()
    if isinstance(node,list):
        for n in node:collect_refs(n,origin,resolver,seen)
    elif isinstance(node,dict):
        if '$ref' in node:
            value,target=resolver.resolve(origin,node['$ref'])
            key=(str(target),node['$ref'])
            if key not in seen:
                seen.add(key)
                if not value.get('_manifest_only') if isinstance(value,dict) else True:
                    collect_refs(value,target,resolver,seen)
        for k,v in node.items():
            if k!='$ref':collect_refs(v,origin,resolver,seen)

def check_oas_shape(path,data,resolver):
    assert data.get('openapi')=='3.1.0',f'{path}: not OAS 3.1.0'
    assert data.get('info',{}).get('version'),f'{path}: missing info.version'
    assert isinstance(data.get('paths'),dict),f'{path}: missing paths'
    assert isinstance(data.get('components'),dict),f'{path}: missing components'
    seen_ops=set()
    for route, raw in data['paths'].items():
        resolved,target=resolver.resolve(path,raw['$ref']) if '$ref' in raw else (raw,path)
        if resolved.get('_manifest_only'):
            continue
        assert isinstance(resolved,dict),f'{path}:{route}: non-path object'
        methods=[m for m in resolved if m in METHODS]
        for m in methods:
            operation=resolved[m]
            assert 'operationId' in operation,f'{path}:{route}:{m}: no operationId'
            oid=operation['operationId']
            assert oid not in seen_ops,f'{path}: duplicate operationId {oid}'
            seen_ops.add(oid)
            assert 'responses' in operation,f'{path}:{route}:{m}: no responses'
            cmd=operation.get('x-opal-cli',resolved.get('x-opal-cli',{}).get(m))
            assert cmd and cmd.get('command'),f'{path}:{route}:{m}: missing x-opal-cli'
            for key in re.findall(r'{([^}]+)}',route):
                parameters=resolved.get('parameters',[])+operation.get('parameters',[])
                found=[]
                for p in parameters:
                    q=resolver.resolve(target,p['$ref'])[0] if '$ref' in p else p
                    if q.get('_manifest_only'):continue
                    if q.get('name')==key and q.get('in')=='path' and q.get('required'):found.append(q)
                assert found, f'{path}:{route}:{m}: missing required path parameter {key}'
            # Both operation and Path Item inherited response errors must have correlation headers.
            for status,r in operation['responses'].items():
                if '$ref' in r:
                    r,t=resolver.resolve(target,r['$ref'])
                    if r.get('_manifest_only'):continue
                assert isinstance(r,dict),f'{path}:{route}:{m}:{status}: invalid response'
                if status[0] in '245':
                    keys=set(r.get('headers',{}))
                    must={'X-Opal-Session-Id','X-Opal-Transaction-Id','X-Opal-Request-Id','X-Opal-Causation-Id'}
                    assert must <= keys,f'{path}:{route}:{m}:{status}: incomplete correlation response headers'
    return len(seen_ops)

def check(strict=False,verbose=True):
    r=Resolver(strict)
    for path in SPECS:
        d=r.load(path)
        collect_refs(d,path,r)
    by_engine={}
    for path in SPECS[1:]:
        d=r.load(path)
        by_engine[path.stem]=check_oas_shape(path,d,r)
        for n in ['predict','train','validate','export','benchmark']:
            p='/api/v1/predict' if n=='predict' else f'/api/v1/{n}/'
            assert p in d['paths'],f'{path}: missing {p}'
            request=d['paths'][p]['post']['requestBody']['content']['application/json']['schema']['$ref']
            target, _=r.resolve(path,request)
            assert any('engine_options' in part.get('properties',{}) for part in target['allOf']),f'{path}: no typed engine options on {p}'
        assert d['paths']['/api/v1/engine/']['$ref'].endswith('opal_kernel.yaml#/components/pathItems/engines_collection')
    if verbose:
        print(f'PASS: parsed {len(SPECS)} OpenAPI 3.1 specs')
        print(f'PASS: resolved internal/vision refs; suite symbols: {r.full_kernel_refs} real OPAL refs, {r.known_kernel_manifest_refs} manifest-only refs')
        print('PASS: engine paths/operationIDs/correlation mappings:',by_engine)
        print('PASS: typed engine extensions for predict/train/validate/export/benchmark')
        if r.known_kernel_manifest_refs:print('LIMITATION: full upstream OPAL kernel unavailable; source-level suite compatibility NOT fully validated')
        else:print('PASS: upstream kernel file references resolved')
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--strict',action='store_true',help='Fail unless full upstream opal_kernel.yaml exists and resolves')
    args=p.parse_args()
    try:check(args.strict)
    except (ContractIssue,AssertionError,KeyError,ValueError) as e:
        print('FAIL:',e,file=sys.stderr);sys.exit(1)
