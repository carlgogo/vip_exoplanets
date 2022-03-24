"""
Update intro text in documentation using text in README.rst

"""


with open("README.rst") as f_r:
    readme = f_r.readlines()
str_titles = ['TL;DR', 
              'Installation and dependencies',
              'Image conventions',
              'Mailing list',
              'Attribution',
              'THE END']

for i in range(len(str_titles)-1):    
    start_write=False
    stop_write=False
    with open("docs/source/trimmed_readme_{}.rst".format(i+1), 'w') as f_i:
        for l, line in enumerate(readme):
            if start_write and not str_titles[i+1] in line and not stop_write:
                f_i.write(line)
            elif str_titles[i] in line and not stop_write:
                f_i.write(line)
                start_write=True
            elif str_titles[i+1] in line:
                stop_write=True
            else:
                continue
            
            
print("successfully converted README into documentation rst files.")
