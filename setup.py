from setuptools import setup

setup(name="carle",\
        packages=["carle", "tests", "evaluation"],\
        install_requires=["numpy==2.2.4",\
                        "torch==2.6.0",\
                        "scikit-image==0.25.2",\
                        "matplotlib==3.10.1"],\
        version="0.0.2")




