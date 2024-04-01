# sequence_extensions

provides high order functions as extesions for the custom list class in python

```python 
l = list_ext([1, 2, 3, 4])

l.map(lambda x: x*2)
[2, 4, 6, 8]

l.filter(lambda x: x%2==0)
[2, 4]

l.for_each(lambda x: print(x))
1
2
3
4

l.first(lambda x: x%2==0)
2

l.last(lambda x: x%2==0)
4

l.to_strings()
["1", "2", "3", "4"]

l.to_string()
"1, 2, 3, 4"

```


for develompment install 
pip install -e .

to run tests
pytest

To generate coverage
pytest --cov  --cov-report html

