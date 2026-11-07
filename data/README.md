# Данные

Данные организатора в репозиторий не кладём. Распакуйте архив кейса так, чтобы получилось:

```
data/sample/packages/P01/*.txt
data/sample/questions.csv
data/sample/answers_public.json
data/sample/check.py
```

```bash
unzip school21-onsoft-data.zip -d /tmp/onsoft && mv /tmp/onsoft/school21-onsoft-data data/sample
```

Без этой папки бэк запускается, но датасета `sample` не будет — загрузите архив через `/api/datasets`.
