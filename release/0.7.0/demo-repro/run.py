import yaml
cfg = yaml.safe_load(open('config.yaml'))
print('top_k', cfg['retrieval']['top_k'])
