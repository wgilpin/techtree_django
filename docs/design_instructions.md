The app is complex. In every app folder that contains python code, there should be a markdown file, "design.md" that contains:

The folder relative path

A name describing the responsibilities of the code in the folder

A paragraph describing the role of this code

A list of files, with a short description of the role of that file - skip all test* files
- for each file a list of public methods, but not methods beginning with _ (underscore)
  - for each public method, a one line description


There should also be a single top level file, `design.md`, in the docs/ folder, that contains the hierarchical summary of all the `design.md` files in every folder.

This top level file, for each folder design file, contains 
* the folder path
* title
* description paragraph.