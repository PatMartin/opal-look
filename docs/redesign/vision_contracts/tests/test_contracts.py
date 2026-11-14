from pathlib import Path
import sys
import yaml
import pytest
from jsonschema import Draft202012Validator
sys.path.insert(0,str(Path(__file__).parent))
from check_contracts import check, OPENAPI

FAMILIES=['yolo','rfdetr','rtdetr','dfine']

def test_refs_and_opal_conventions():
    check(strict=False,verbose=False)

@pytest.mark.parametrize('family',FAMILIES)
@pytest.mark.parametrize('task',['predict','train','validate','export','benchmark'])
def test_typed_engine_options_are_closed(family,task):
    file=OPENAPI/'engines'/f'{family}.yaml'
    spec=yaml.safe_load(file.read_text())
    route='/api/v1/predict' if task=='predict' else f'/api/v1/{task}/'
    request=spec['paths'][route]['post']['requestBody']['content']['application/json']['schema']['$ref']
    request=spec['components']['schemas'][request.split('/')[-1]]
    opts=request['allOf'][1]['properties']['engine_options']['$ref']
    schema=spec['components']['schemas'][opts.split('/')[-1]]
    Draft202012Validator.check_schema(schema)
    assert schema['additionalProperties'] is False
    assert list(Draft202012Validator(schema).iter_errors({'unknown_option':True})), 'unadvertised options must reject'
    if schema['properties']:
        first=next(iter(schema['properties']))
        # Lack of a required field is valid; semantics can be capability gated.
        assert not list(Draft202012Validator(schema).iter_errors({}))

@pytest.mark.parametrize('family',FAMILIES)
def test_no_silent_model_distribution(family):
    d=yaml.safe_load((OPENAPI/'engines'/f'{family}.yaml').read_text())
    assert '/api/v1/model/{model_id}/install' in d['paths']
    assert '/api/v1/predict' in d['paths']
    # Explicit installation is separate from prediction.
    pred=str(d['paths']['/api/v1/predict']).lower()
    assert 'install' not in pred


def test_geometry_bbox_schema():
    v=yaml.safe_load((OPENAPI/'shared'/'vision_kernel.yaml').read_text())
    bbox=v['components']['schemas']['BoundingBox']
    Draft202012Validator.check_schema(bbox)
    good={'type':'bbox','format':'xyxy','coordinate_system':'image_pixels','values':[1,2,3,4]}
    assert not list(Draft202012Validator(bbox).iter_errors(good))
    assert list(Draft202012Validator(bbox).iter_errors({**good,'values':[1,2]}))


def test_yolo_has_real_native_extensions_only():
    paths=yaml.safe_load((OPENAPI/'engines'/'yolo.yaml').read_text())['paths']
    assert {'/api/v1/track/','/api/v1/tune/','/api/v1/solution/run'} <= set(paths)
    for family in ['rfdetr','rtdetr','dfine']:
        p=yaml.safe_load((OPENAPI/'engines'/f'{family}.yaml').read_text())['paths']
        assert '/api/v1/track/' not in p
        assert '/api/v1/tune/' not in p
        assert '/api/v1/segment/' not in p, 'task aliases must not create duplicate REST endpoints'


def test_common_kernel_is_not_a_service():
    v=yaml.safe_load((OPENAPI/'shared'/'vision_kernel.yaml').read_text())
    assert v['paths']=={}
    assert 'pathItems' in v['components']
