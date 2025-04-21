# -*- coding: utf-8

echo "Long Files"
# list  all python files > 500 lines
wc -l core/*.py | awk '$1 > 500 && $2 != "total" { print }'
wc -l lessons/*.py | awk '$1 > 500 && $2 != "total" { print }'
wc -l quiz/*.py | awk '$1 > 500 && $2 != "total" { print }'
wc -l onboarding/*.py | awk '$1 > 500 && $2 != "total" { print }'
wc -l syllabus/*.py | awk '$1 > 500 && $2 != "total" { print }'