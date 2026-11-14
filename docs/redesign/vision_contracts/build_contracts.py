#!/usr/bin/env python3
"""Generate draft OPAL-compatible vision contracts from one explicit model.

Generated files are design artifacts, not an implementation or publication.
Requires PyYAML. The authoritative OPAL kernel remains external.
"""
from pathlib import Path
from copy import deepcopy
import yaml

ROOT=Path(__file__).parent
SHARED=ROOT/'openapi'/'shared'
ENGINES=ROOT/'openapi'/'engines'
VK='vision_kernel.yaml'
OPAL='./opal_kernel.yaml'
VER='0.1.0-draft'


def ref(loc):return {'$ref':loc}
def sref(name):return ref(f'#/components/schemas/{name}')
def vref(name):return ref(f'../shared/vision_kernel.yaml#/components/schemas/{name}')
def kr(name,typ='responses'):return ref(f'{OPAL}#/components/{typ}/{name}')
def param(name, typ='string', **kw):return dict(name=name, **{'in':'path','required':True}, schema=dict(type=typ,**kw))
def obj(props=None, required=None, *, extra=False, description=None):
 d={'type':'object','properties':props or {},'additionalProperties':extra}
 if required:d['required']=required
 if description:d['description']=description
 return d

def str_(**kw):return {'type':'string',**kw}
def num(**kw):return {'type':'number',**kw}
def integer(**kw):return {'type':'integer',**kw}
def arr(items, **kw):return {'type':'array','items':items,**kw}
def enum(*v):return {'type':'string','enum':list(v)}
def jref(typ):return {'content': {'application/json': {'schema':sref(typ)}}}
def req(typ, required=True):return {'required':required,**jref(typ)}
def response(status,desc, schema=None, *, headers=True):
 d={'description':desc}
 if schema:d['content']={'application/json':{'schema':sref(schema)}}
 if headers:d['headers']=CORR_RESP.copy()
 return d
CORR_PARAMS=[kr(x,'parameters') for x in ['OpalSessionIdParameter','OpalTransactionIdParameter','OpalRequestIdParameter','OpalCausationIdParameter']]
CORR_RESP={n:kr(n.replace('X-Opal-','Opal')+'Header','headers') for n in []} # defined explicitly below
CORR_RESP={'X-Opal-Session-Id':kr('OpalSessionIdHeader','headers'), 'X-Opal-Transaction-Id':kr('OpalTransactionIdHeader','headers'), 'X-Opal-Request-Id':kr('OpalRequestIdHeader','headers'), 'X-Opal-Causation-Id':kr('OpalCausationIdHeader','headers')}
ERR_CODES={'400':'BadRequest','401':'Unauthorized','403':'Forbidden','404':'NotFound','409':'Conflict','412':'PreconditionFailed','413':'PayloadTooLarge','422':'UnprocessableEntity','428':'PreconditionRequired','429':'TooManyRequests','503':'ServiceUnavailable'}

def op(method, opid, tag, summary, cli=None, *, body=None, status='200', resp=None, params=None, errors=None, description=None, idempotent=False, etag=False):
 d={'tags':[tag],'operationId':opid,'summary':summary}
 if description:d['description']=description
 if cli:d['x-opal-cli']=cli
 if params:d['parameters']=params
 if body:d['requestBody']=req(body)
 d['responses']={status:response(status, {'200':'Success.','201':'Resource created.','202':'Operation accepted.','204':'Resource removed.'}.get(status,'Success.'),resp)}
 if status in ('201','202'):d['responses'][status]['headers']['Location']=kr('Location','headers')
 if etag:d['responses'][status]['headers']['ETag']=kr('ETag','headers')
 if errors is None: errors=['400','401','403','409','422','429','503']
 for e in errors:d['responses'][e]=kr(ERR_CODES[e])
 if idempotent:d.setdefault('parameters',[]).append(kr('IdempotencyKey','parameters'))
 return d

def item(methods, *, parameters=None):
 d={}
 if parameters:d['parameters']=CORR_PARAMS+parameters
 else:d['parameters']=list(CORR_PARAMS)
 d['x-opal-cli']={method:deepcopy(od.pop('x-opal-cli')) for method,od in methods.items() if 'x-opal-cli' in od}
 d.update(methods)
 return d

def cli(group,cmd, parent=None,aliases=None):
 d={'group':group,'command':cmd}
 if parent:d['parent']=parent
 if aliases:d['aliases']=aliases
 return d

S={}
S['VisionCapabilities']=obj({'engine_id':str_(),'engine_family':enum('yolo','rfdetr','rtdetr','dfine'), 'implementation':str_(),'version':str_(), 'tasks':arr(str_()), 'operations':arr(str_()),'runtimes':arr(str_()),'extension_schemas':obj(extra=True),'instances':arr(str_()),'available':{'type':'boolean'}},['engine_id','engine_family','implementation','version','tasks','operations','available'],extra=True,description='Capabilities are instance-level observations, not guarantees for each model or runtime.')
S['VisionRuntime']=obj({'runtime_id':str_(),'implementation':str_(),'version':str_(),'operations':arr(str_()),'devices':arr(str_()),'available':{'type':'boolean'},'limitations':arr(str_())},['runtime_id','implementation','available'],extra=True)
S['VisionModel']=obj({'model_id':str_(),'logical_id':str_(),'engine_id':str_(),'name':str_(),'version':str_(),'weights_sha256':str_(pattern='^[a-fA-F0-9]{64}$'),'tasks':arr(str_()),'operations':arr(str_()),'runtimes':arr(str_()),'status':enum('available','unavailable','stale','unknown'),'loaded':{'type':'boolean'},'bytes':integer(minimum=0),'created_at':str_(format='date-time')},['model_id','engine_id','name','tasks','status'],extra=True)
S['ModelInstallation']=obj({'installation_id':str_(),'model_id':str_(),'instance_id':str_(),'host':str_(),'runtime':str_(),'status':enum('available','unavailable','stale','unknown'),'last_seen':str_(format='date-time'),'weights_sha256':str_()},['installation_id','model_id','instance_id','status'],extra=True)
S['ModelInstallRequest']=obj({'model':str_(),'version':str_(),'source_uri':str_(format='uri'),'expected_sha256':str_(),'agree_to_license':{'type':'boolean','default':False}},['model'],extra=False,description='Explicit install only. No implicit downloading during predict.')
S['ModelLoadRequest']=obj({'runtime':str_(),'device':str_(),'residency':enum('on-demand','keep-loaded','idle-timeout'),'idle_timeout_seconds':integer(minimum=1)},extra=False)
S['VisionSource']=obj({'kind':enum('uri','host_path','inline','artifact','device'),'uri':str_(),'host_path':str_(),'base64':str_(),'media_type':str_(),'artifact_id':str_(),'device_id':str_()},['kind'],extra=False,description='Exactly one locator matching kind MUST be populated. Local paths are not assumed visible remotely. URI schemes and network access are policy-controlled.')
S['FrameEnvelope']=obj({'frame_id':str_(),'source_id':str_(),'pipeline_run_id':str_(),'sequence':integer(minimum=0),'captured_at':str_(format='date-time'),'width':integer(minimum=1),'height':integer(minimum=1),'session_id':str_(),'transaction_id':str_(),'request_id':str_(),'causation_id':str_()},['frame_id','width','height'],extra=True)
S['Point']=obj({'x':num(),'y':num()},['x','y'])
S['BoundingBox']=obj({'type':{'const':'bbox'},'format':{'const':'xyxy'},'coordinate_system':{'const':'image_pixels'},'values':arr(num(),minItems=4,maxItems=4)},['type','format','coordinate_system','values'])
S['OrientedBox']=obj({'type':{'const':'obb'},'coordinate_system':{'const':'image_pixels'},'cx':num(),'cy':num(),'width':num(minimum=0),'height':num(minimum=0),'angle_rad':num()},['type','coordinate_system','cx','cy','width','height','angle_rad'])
S['Polygon']=obj({'type':{'const':'polygon'},'coordinate_system':{'const':'image_pixels'},'points':arr(sref('Point'),minItems=3)},['type','coordinate_system','points'])
S['MaskGeometry']=obj({'type':{'const':'mask'},'coordinate_system':{'const':'image_pixels'},'width':integer(minimum=1),'height':integer(minimum=1),'encoding':enum('rle','polygon','artifact'),'rle':obj(extra=True),'polygons':arr(sref('Polygon')),'artifact':sref('VisionArtifactRef')},['type','coordinate_system','width','height','encoding'],extra=False)
S['Keypoint']=obj({'name':str_(),'x':num(),'y':num(),'confidence':num(minimum=0,maximum=1),'visible':{'type':'boolean'}},['x','y'],extra=False)
S['KeypointSet']=obj({'type':{'const':'keypoints'},'coordinate_system':{'const':'image_pixels'},'keypoints':arr(sref('Keypoint'))},['type','coordinate_system','keypoints'])
S['Geometry']={'oneOf':[sref(n) for n in ['BoundingBox','OrientedBox','Polygon','MaskGeometry','KeypointSet']], 'description':'Canonical pixel coordinates refer to orientation-corrected original source frame.'}
S['ClassIdentity']=obj({'native_class_id':{'oneOf':[str_(),integer()]},'native_name':str_(),'canonical_id':str_(),'taxonomy_version':str_()},['native_class_id'],extra=False)
S['Detection']=obj({'detection_id':str_(),'class':sref('ClassIdentity'),'confidence':num(minimum=0,maximum=1),'geometry':sref('Geometry'),'contributing_models':arr(str_()),'track_id':str_()},['class','confidence','geometry'],extra=True)
S['VisionArtifactRef']=obj({'artifact_id':str_(),'media_type':str_(),'size_bytes':integer(minimum=0),'uri':str_(),'expires_at':str_(format='date-time'),'sha256':str_()},['artifact_id','media_type','size_bytes','uri'],extra=False)
S['PredictionCore']=obj({'model_id':str_(),'source':sref('VisionSource'),'task':enum('detect','segment','classify','pose','obb','depth','embed'),'runtime':str_(),'device':str_(),'include_native':{'type':'boolean','default':False},'output_mode':enum('auto','inline','reference'),'options':obj({'confidence':num(minimum=0,maximum=1),'iou':num(minimum=0,maximum=1),'image_size':integer(minimum=1),'classes':arr(integer())},extra=True)},['model_id','source','task'],extra=True)
S['PredictionRequest']={'allOf':[sref('PredictionCore'),obj({'engine_options':obj(extra=True)},extra=True)],'description':'Generic base; engine contracts override engine_options with a typed schema.'}
S['PredictionResult']=obj({'engine_id':str_(),'instance_id':str_(),'model_id':str_(),'runtime':str_(),'task':str_(),'frame':sref('FrameEnvelope'),'detections':arr(sref('Detection')),'classifications':arr(obj({'class':sref('ClassIdentity'),'probability':num(minimum=0,maximum=1)},['class','probability'])),'artifacts':arr(sref('VisionArtifactRef')),'coordinate_transform':obj(extra=True),'native':obj({'format':str_(),'data':obj(extra=True)},extra=True),'execution_id':str_()},['engine_id','instance_id','model_id','task','frame'],extra=True,description='Normalizes common results; native included only on explicit request, bounded by output policy.')
S['TrainingCore']=obj({'model_id':str_(),'dataset_uri':str_(),'epochs':integer(minimum=1),'batch_size':integer(minimum=1),'seed':integer(),'resume_from':str_(),'runtime':str_(),'device':str_()},['model_id','dataset_uri'],extra=True)
S['ValidationCore']=obj({'model_id':str_(),'dataset_uri':str_(),'split':str_(),'device':str_()},['model_id','dataset_uri'],extra=True)
S['ExportCore']=obj({'model_id':str_(),'format':str_(),'runtime':str_(),'device':str_(),'precision':enum('fp32','fp16','int8')},['model_id','format'],extra=True)
S['BenchmarkCore']=obj({'model_id':str_(),'dataset_uri':str_(),'device':str_(),'runtime':str_(),'batch_size':integer(minimum=1),'warmup_iterations':integer(minimum=0),'iterations':integer(minimum=1),'measure':enum('model-only','end-to-end')},['model_id'],extra=True)
S['JobRequest']=obj({'operation':enum('train','validate','export','benchmark','tune'),'parameters':obj(extra=True),'model_id':str_()},['operation','parameters'],extra=False)
S['VisionJob']=obj({'job_id':str_(),'operation':str_(),'engine_id':str_(),'instance_id':str_(),'state':enum('queued','running','succeeded','failed','cancelled','cancel_requested'),'created_at':str_(format='date-time'),'updated_at':str_(format='date-time'),'result_artifacts':arr(sref('VisionArtifactRef')),'error':kr('OpalErrorBody','schemas')},['job_id','operation','engine_id','state','created_at'],extra=True)
S['VisionMetrics']=obj({'latency_p50_ms':num(minimum=0),'latency_p95_ms':num(minimum=0),'latency_p99_ms':num(minimum=0),'throughput_fps':num(minimum=0),'precision':num(minimum=0,maximum=1),'recall':num(minimum=0,maximum=1),'map50':num(minimum=0,maximum=1),'map50_95':num(minimum=0,maximum=1),'peak_memory_mb':num(minimum=0),'model_size_mb':num(minimum=0),'warmup_ms':num(minimum=0),'native':obj(extra=True)},extra=True)
S['BenchmarkResult']=obj({'benchmark_id':str_(),'engine_id':str_(),'model_id':str_(),'dataset_uri':str_(),'runtime':str_(),'device':str_(),'precision':str_(),'resolution':arr(integer(),minItems=2,maxItems=2),'batch_size':integer(minimum=1),'measurement_scope':enum('model-only','end-to-end'),'metrics':sref('VisionMetrics'),'execution_id':str_()},['benchmark_id','engine_id','model_id','runtime','device','measurement_scope','metrics'],extra=False)
S['ExecutionManifest']=obj({'execution_id':str_(),'engine_id':str_(),'implementation':str_(),'engine_version':str_(),'instance_id':str_(),'model_id':str_(),'model_sha256':str_(),'runtime':str_(),'device':str_(),'effective_parameters':obj(extra=True),'input_sha256':str_(),'input_reference':str_(),'random_seed':integer(),'fallback_history':arr(obj(extra=True)),'pipeline_run_id':str_(),'artifacts':arr(sref('VisionArtifactRef')),'created_at':str_(format='date-time')},['execution_id','engine_id','instance_id','model_id','runtime','created_at'],extra=True)
S['ReproduceRequest']=obj({'verify_only':{'type':'boolean','default':True},'allow_stateful_replay':{'type':'boolean','default':False}},extra=False,description='Requires explicit consent to rerun stateful operations; validates resources and permissions.')
S['LogRead']=obj({'job_id':str_(),'lines':arr(str_())},['job_id','lines'])
S['InstallResult']=obj({'job_id':str_(),'model_id':str_(),'status':str_()},['job_id','model_id','status'])
S['ArtifactRead']=obj({'artifact':sref('VisionArtifactRef'),'status':str_()},['artifact','status'])

P={}
P['capabilities']=item({'get':op('get','vision_capabilities_get','capabilities','Discover engine instance capabilities',cli('engines','capabilities'),resp='VisionCapabilities',errors=['401','403','503'])})
P['models_collection']=item({'get':op('get','vision_models_list','models','List available models (bounded catalog)',cli('models','list'),resp=None,errors=['401','403','503'])})
P['models_collection']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('VisionModel'))}}
P['models_collection']['get']['parameters']=[{'name':'loaded','in':'query','required':False,'schema':{'type':'boolean'}},{'name':'task','in':'query','required':False,'schema':{'type':'string'}}]
P['model_item']=item({'get':op('get','vision_model_show','models','Show model',cli('models','show'),resp='VisionModel',errors=['401','403','404','503']),
 'delete':op('delete','vision_model_remove','models','Remove this installation after dependency check',cli('models','remove'),status='204',params=[kr('IfMatch','parameters')],errors=['401','403','404','409','412','422','428','503'])},parameters=[param('model_id')])
P['model_item']['delete']['parameters'].append({'name':'dry_run','in':'query','required':False,'schema':{'type':'boolean','default':False},'description':'Validate dependencies and report effects without removing the installation.'})
P['model_capabilities']=item({'get':op('get','vision_model_capabilities','models','Show model task/runtime capabilities',cli('models','capabilities'),resp='VisionCapabilities',errors=['401','403','404','503'])},parameters=[param('model_id')])
P['model_install']=item({'post':op('post','vision_model_install','models','Install one version explicitly',cli('models','install'),body='ModelInstallRequest',status='202',resp='InstallResult',errors=['400','401','403','409','422','429','503'],idempotent=True)},parameters=[param('model_id')])
P['model_load']=item({'post':op('post','vision_model_load','models','Load model into engine memory',cli('models','load'),body='ModelLoadRequest',status='202',resp='VisionJob',errors=['401','403','404','409','422','429','503'],idempotent=True)},parameters=[param('model_id')])
P['model_unload']=item({'post':op('post','vision_model_unload','models','Unload model if unused',cli('models','unload'),status='202',resp='VisionJob',errors=['401','403','404','409','422','429','503'])},parameters=[param('model_id')])
P['model_versions']=item({'get':op('get','vision_model_versions','models','List known immutable model versions',cli('models','versions'),errors=['401','403','404','503'])},parameters=[param('model_id')])
P['model_versions']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('VisionModel'))}}
P['model_installations']=item({'get':op('get','vision_model_installations','models','List known installations for this model',cli('models','instances'),errors=['401','403','404','503'])},parameters=[param('model_id')])
P['model_installations']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('ModelInstallation'))}}
P['runtimes']=item({'get':op('get','vision_runtimes_list','runtimes','List supported runtimes',cli('runtimes','list'),errors=['401','403','503'])})
P['runtimes']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('VisionRuntime'))}}
P['runtime_item']=item({'get':op('get','vision_runtime_show','runtimes','Inspect runtime capabilities',cli('runtimes','show'),resp='VisionRuntime',errors=['401','403','404','503'])},parameters=[param('runtime_id')])
P['jobs_collection']=item({'get':op('get','vision_jobs_list','jobs','List jobs',cli('jobs','list'),errors=['401','403','503']),
 'post':op('post','vision_jobs_create','jobs','Create asynchronous job',cli('jobs','create'),body='JobRequest',status='202',resp='VisionJob',idempotent=True)})
P['jobs_collection']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('VisionJob'))}}
P['jobs_item']=item({'get':op('get','vision_job_show','jobs','Inspect job state',cli('jobs','show'),resp='VisionJob',errors=['401','403','404','503'])},parameters=[param('job_id')])
P['jobs_cancel']=item({'post':op('post','vision_job_cancel','jobs','Request cancellation',cli('jobs','cancel'),status='202',resp='VisionJob',errors=['401','403','404','409','503'])},parameters=[param('job_id')])
P['jobs_logs']=item({'get':op('get','vision_job_logs','jobs','Read job logs',cli('jobs','logs'),resp='LogRead',errors=['401','403','404','503'])},parameters=[param('job_id')])
P['artifact_item']=item({'get':op('get','vision_artifact_show','artifacts','Read artifact metadata',cli('artifacts','show'),resp='ArtifactRead',errors=['401','403','404','503'])},parameters=[param('artifact_id')])
P['artifact_content']=item({'get':op('get','vision_artifact_download','artifacts','Download artifact bytes',cli('artifacts','download'),errors=['401','403','404','503'])},parameters=[param('artifact_id')])
P['artifact_content']['get']['responses']['200']['content']={'application/octet-stream':{'schema':str_(format='binary')}}
P['executions']=item({'get':op('get','vision_executions_list','executions','List recent execution manifests',cli('executions','list'),errors=['401','403','503'])})
P['executions']['get']['responses']['200']['content']={'application/json':{'schema':arr(sref('ExecutionManifest'))}}
P['execution_item']=item({'get':op('get','vision_execution_show','executions','Inspect execution metadata',cli('executions','show'),resp='ExecutionManifest',errors=['401','403','404','503'])},parameters=[param('execution_id')])
P['execution_manifest']=item({'get':op('get','vision_execution_manifest','executions','Fetch reproducibility manifest',cli('executions','manifest'),resp='ExecutionManifest',errors=['401','403','404','503'])},parameters=[param('execution_id')])
P['execution_reproduce']=item({'post':op('post','vision_execution_reproduce','executions','Reproduce a recorded operation when explicitly permitted',cli('executions','reproduce'),body='ReproduceRequest',status='202',resp='VisionJob',errors=['401','403','404','409','422','503'],idempotent=True)},parameters=[param('execution_id')])

# reusable common operation templates: engines may override only the body schema for typed engine_options.
for method,name,tag,command,core,rest in [
 ('post','predict','inference','predict','PredictionRequest','PredictionResult'),
 ('post','train','training','train','TrainingCore','VisionJob'),
 ('post','validate','training','validate','ValidationCore','VisionJob'),
 ('post','export','deployment','export','ExportCore','VisionJob'),
 ('post','benchmark','benchmark','benchmark','BenchmarkCore','VisionJob')]:
 status='200' if name=='predict' else '202'
 P[name]=item({method:op(method,f'vision_{name}',tag,f'{name.title()} using installed model',cli(None,command) if False else {'command':command},body=core,resp=rest,status=status,idempotent=status=='202')})
P['predict']['post']['description']='Synchronous single-input inference; task selected in request body. Native data is optional and bounded. Specialized native workflows use separate operations.'

V={'openapi':'3.1.0','jsonSchemaDialect':'https://json-schema.org/draft/2020-12/schema','info':{'title':'OPAL Vision Kernel (reusable, not standalone)','version':VER,'description':'Domain-specific reusable components and Path Items. MUST be consumed with the authoritative opal_kernel.yaml; never publish this as a standalone REST service. Shared functionality only; engine-specific request schemas specialize common operation contracts.'},'paths':{},'x-vision-composition':{'suite_kernel':'./opal_kernel.yaml','reuse_model':'External $refs and typed schema composition; do not merge kernels','cli_compatibility':'x-opal-cli per OPAL suite v1.7.1'},'components':{'schemas':S,'pathItems':P}}

def write_yaml(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w') as f:yaml.safe_dump(data,f,sort_keys=False,allow_unicode=True,width=110)
write_yaml(SHARED/VK,V)

# Engine-owned typed extensions; schema properties vary only where behavior actually varies.
E={
 'yolo':{
   'name':'Ultralytics YOLO','tasks':['detect','segment','classify','pose','obb'],'predict':{'augment':{'type':'boolean'},'retina_masks':{'type':'boolean'},'agnostic_nms':{'type':'boolean'},'max_det':integer(minimum=1),'half':{'type':'boolean'}},
   'train':{'optimizer':str_(),'freeze_layers':arr(integer(minimum=0)),'cos_lr':{'type':'boolean'},'patience':integer(minimum=0)},
   'validate':{'plots':{'type':'boolean'},'save_json':{'type':'boolean'}},
   'export':{'dynamic':{'type':'boolean'},'simplify':{'type':'boolean'},'opset':integer(minimum=1)},
   'benchmark':{'half':{'type':'boolean'},'int8':{'type':'boolean'}},'native':['track','tune','solutions']},
 'rfdetr':{
   'name':'Roboflow RF-DETR','tasks':['detect','segment','pose'],'predict':{'resolution':integer(minimum=1),'threshold':num(minimum=0,maximum=1)},
   'train':{'gradient_accumulation_steps':integer(minimum=1),'learning_rate':num(exclusiveMinimum=0),'early_stopping':{'type':'boolean'}},
   'validate':{'evaluation_config':str_()},'export':{'input_shape':arr(integer(minimum=1),minItems=2,maxItems=2)},
   'benchmark':{'amp':{'type':'boolean'}},'native':[],'notes':'Pose/keypoint functionality is preview/model-dependent; every operation is capability gated.'},
 'rtdetr':{
   'name':'RT-DETR / RT-DETRv2','tasks':['detect'],'predict':{'decoder_layers':integer(minimum=1),'num_queries':integer(minimum=1)},
   'train':{'config_uri':str_(),'ema':{'type':'boolean'},'distributed':{'type':'boolean'}},
   'validate':{'coco_metrics':{'type':'boolean'}},'export':{'exporter_config':str_()},
   'benchmark':{'decoder_layers':integer(minimum=1)},'native':[], 'notes':'Decoder and query controls are optional and must be advertised by the selected implementation; never assume all RT-DETR backends support them.'},
 'dfine':{
   'name':'D-FINE','tasks':['detect'],'predict':{'postprocess_config':str_()},
   'train':{'config_uri':str_(),'teacher_checkpoint':str_(),'distributed':{'type':'boolean'}},
   'validate':{'coco_metrics':{'type':'boolean'}},'export':{'exporter_config':str_()},
   'benchmark':{'profile_layers':{'type':'boolean'}},'native':[],
   'notes':'FDR and GO-LSD are architecture/training mechanisms, not assumed request-time inference switches.'}}

SPECIALIZED={
 'predict':('PredictionCore','PredictionResult','200','inference'),
 'train':('TrainingCore','VisionJob','202','training'),
 'validate':('ValidationCore','VisionJob','202','training'),
 'export':('ExportCore','VisionJob','202','deployment'),
 'benchmark':('BenchmarkCore','VisionJob','202','benchmark')}

for family,ed in E.items():
 out={'openapi':'3.1.0','jsonSchemaDialect':'https://json-schema.org/draft/2020-12/schema',
  'info':{'title':f'OPAL-compatible {ed["name"]} Standalone REST Adapter','version':VER,'description':f'Contract-first adapter for {ed["name"]}; independently deployable with no opal-look or opal-devices runtime dependency. Shared vision domain semantics derive from vision_kernel.yaml and suite-wide conventions from opal_kernel.yaml. {ed.get("notes","")}'},
  'servers':[{'url':'http://127.0.0.1:8000','description':'Illustrative loopback server; host/port configured by deployment'}],
  'tags':[{'name':x} for x in ['capabilities','engines','models','inference','training','deployment','benchmark','jobs','runtimes','artifacts','executions']],
  'x-vision-engine':{'family':family,'supported_task_families':ed['tasks'],'native_operations':ed['native'],'capability_gating':True},
  'security':[{'BearerAuth':[]}],
  'components':{'securitySchemes':{'BearerAuth':ref('../shared/opal_kernel.yaml#/components/securitySchemes/BearerAuth')},'schemas':{}},
  'paths':{}}
 paths=out['paths']
 # OPAL suite root Path Items (reuse as-is; existing OPAL conventions)
 for name,path in [('health','/api/v1/health/'),('health_live','/api/v1/health/live'),('health_ready','/api/v1/health/ready'),('info','/api/v1/info/'),('info_ping','/api/v1/info/ping'),('engines_collection','/api/v1/engine/'),('engine_item','/api/v1/engine/{engine_id}'),('settings_collection','/api/v1/setting/'),('settings_key','/api/v1/setting/{key}')]:
  paths[path]=ref(f'../shared/opal_kernel.yaml#/components/pathItems/{name}')
 # Vision kernel mounted path items
 for key,path in [('capabilities','/api/v1/capabilities/'),('models_collection','/api/v1/model/'),('model_item','/api/v1/model/{model_id}'),('model_capabilities','/api/v1/model/{model_id}/capabilities'),('model_install','/api/v1/model/{model_id}/install'),('model_load','/api/v1/model/{model_id}/load'),('model_unload','/api/v1/model/{model_id}/unload'),('model_versions','/api/v1/model/{model_id}/versions/'),('model_installations','/api/v1/model/{model_id}/installations/'),('runtimes','/api/v1/runtime/'),('runtime_item','/api/v1/runtime/{runtime_id}'),('jobs_collection','/api/v1/job/'),('jobs_item','/api/v1/job/{job_id}'),('jobs_cancel','/api/v1/job/{job_id}/cancel'),('jobs_logs','/api/v1/job/{job_id}/logs'),('artifact_item','/api/v1/artifact/{artifact_id}'),('artifact_content','/api/v1/artifact/{artifact_id}/content'),('executions','/api/v1/execution/'),('execution_item','/api/v1/execution/{execution_id}'),('execution_manifest','/api/v1/execution/{execution_id}/manifest'),('execution_reproduce','/api/v1/execution/{execution_id}/reproduce')]:
  paths[path]=ref(f'../shared/vision_kernel.yaml#/components/pathItems/{key}')
 # Specialize common operation bodies with genuinely typed engine options.
 for name,(base,result,status,tag) in SPECIALIZED.items():
  engopts=f'{family.title().replace("rfdetr","RFDETR").replace("rtdetr","RTDETR").replace("dfine","DFINE")}{name.title()}Options'
  reqname=f'{family.title()}{name.title()}Request'
  # Some requested parameters are backend-conditional. Discover & validate; never silently ignore.
  sch=obj(ed[name],extra=False,description=f'{ed["name"]} {name} extension options. All fields conditional on engine/model/runtime capabilities.')
  out['components']['schemas'][engopts]=sch
  out['components']['schemas'][reqname]={'allOf':[vref(base),obj({'engine_options':sref(engopts)},extra=True)], 'description':f'Common {name} request, extended with typed {family} options.'}
  operation=op('post',f'{family}_{name}',tag,f'{ed["name"]} {name}',{'command':name},body=reqname,status=status,resp=None,idempotent=status=='202',description='Common operation semantics, specialized request schema. Reject unadvertised engine options with 422.')
  # Replace local common-schema refs for response and OPAL correlation parameter refs in response definitions.
  operation['responses'][status]['content']={'application/json':{'schema':vref(result)}}
  # Add 413 to predict and 429 all
  if name=='predict':operation['responses']['413']=ref('../shared/opal_kernel.yaml#/components/responses/PayloadTooLarge')
  route='/api/v1/predict' if name=='predict' else f'/api/v1/{name}/'
  paths[route]={'parameters':[ref(f'../shared/opal_kernel.yaml#/components/parameters/{p}') for p in ['OpalSessionIdParameter','OpalTransactionIdParameter','OpalRequestIdParameter','OpalCausationIdParameter']],
                'x-opal-cli':{'post':{'command':name}}, 'post':operation}
 # Engine-specific operations only when they are semantically distinct.
 if family=='yolo':
  out['components']['schemas']['YoloTrackRequest']={'allOf':[vref('PredictionCore'),obj({'tracker':enum('bytetrack','botsort'),'persist':{'type':'boolean'},'tracker_config_uri':str_()},extra=True)]}
  out['components']['schemas']['YoloTuneRequest']={'allOf':[vref('TrainingCore'),obj({'iterations':integer(minimum=1),'space':obj(extra=True)},extra=True)]}
  out['components']['schemas']['YoloSolutionRequest']=obj({'solution_id':str_(),'source':vref('VisionSource'),'model_id':str_(),'options':obj(extra=True)},['solution_id','source','model_id'])
  for route,name,tag,body,status,resp in [('/api/v1/track/','track','inference','YoloTrackRequest','202','VisionJob'),('/api/v1/tune/','tune','training','YoloTuneRequest','202','VisionJob'),('/api/v1/solution/run','solutions_run','inference','YoloSolutionRequest','202','VisionJob')]:
   cli_meta={'command':name} if name!='solutions_run' else cli('solutions','run')
   od=op('post',f'yolo_{name}',tag,'YOLO-native '+name.replace('_',' '),cli_meta,body=body,status=status,resp=None,description='Capability-gated native Ultralytics workflow. Does not replace common opal-look tracking/analytics.')
   od['responses'][status]['content']={'application/json':{'schema':vref(resp)}}
   paths[route]={'parameters':[ref(f'../shared/opal_kernel.yaml#/components/parameters/{p}') for p in ['OpalSessionIdParameter','OpalTransactionIdParameter','OpalRequestIdParameter','OpalCausationIdParameter']], 'x-opal-cli':{'post':cli_meta},'post':od}
 def fix_engine_ref(node):
  if isinstance(node,dict):
   for k,v in list(node.items()):
    if k=='$ref' and isinstance(v,str) and v.startswith('./opal_kernel.yaml#'):
     node[k]='../shared/opal_kernel.yaml#'+v.split('#',1)[1]
    else:fix_engine_ref(v)
  elif isinstance(node,list):
   for x in node:fix_engine_ref(x)
 fix_engine_ref(out)
 write_yaml(ENGINES/f'{family}.yaml',out)

print('Wrote vision kernel and engine contracts to',ROOT)
