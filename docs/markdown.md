### Markdown rules

code will be retrieved from db in this format:

\```python\\n        colors = ['red', 'green', 'blue']\\n        for color in colors:\\n            print(color.upper())\\n        ```

and should be rendered

```
        colors = ['red', 'green', 'blue']
        for color in colors:
            print(color.upper())\\n
```

Latex can come as \$...$ or \$$...$$. Don't replace anything within those, they need to be passed as-is to the latex processor in the frontend

