import urllib.request
import os

if not os.path.exists('data/df_producao.csv'):
	print('Baixando base de dados')
	with urllib.request.urlopen('http://www.eliasjacob.com.br/cnj/df_producao.csv') as response, open('data/df_producao.csv', 'wb') as out_file:
		data = response.read() # a `bytes` object
		out_file.write(data)
	print('Concluído download de base de dados')
else:
	print('Dados já existem')
