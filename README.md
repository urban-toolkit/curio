# Curio

<p align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/images/logo.png?raw=true" alt="Curio Logo" width="250"/>
</p>

Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels (code, grammar, GUI elements) to facilitate collaboration across the design and implementation of visual analytics components. The framework allows experts to intertwine preprocessing, managing, and visualization stages while tracking provenance of code and visualizations.

**Curio: A Dataflow-Based Framework for Collaborative Urban Visual Analytics**  
Gustavo Moreira, Maryam Hosseini, Carolina Veiga, Lucas Alexandre, Nico Colaninno, Daniel de Oliveira, Nivan Ferreira, Marcos Lage, Fabio Miranda

Video:

<div align="center">
  <video src="https://github.com/urban-toolkit/curio/assets/2387594/6d29bda8-5e94-4496-a4ae-fd55adff024f" />
</div>



<p align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/images/banner.jpg?raw=true" alt="Curio Use Cases" width="1000"/>
</p>

## Table of contents

1. [Features](#features)
2. [Installation and quick start](#installation-and-quick-start)
    1. [Curio Backend](#curio-backend)
    2. [Python sandbox](#python-sandbox)
    3. [UTK workflow](#utk-workflow)
    4. [Curio frontend](#curio-frontend)
    5. [Ray tracing](#ray-tracing)
3. [First dataflow](#first-dataflow)
4. [Team](#team)
5. [How to contribute](#how-to-make-contributions)

## Features

- Provenance-aware dataflow
- Modularized and collaborative visual analytics
- Support for 2D and 3D maps
- Linked data-driven interactions  
- Integration with [UTK](https://urbantk.org) and [Vega-Lite](https://vega.github.io/vega-lite/)

## Installation and quick start

Because Curio is integrated with UTK it is necessary to add it as a submodule.

```console
git clone git@github.com:urban-toolkit/curio.git  
git submodule init
git submodule update --remote --merge
```

Curio is divided into three components: backend (provenance and database management), python sandbox (to run python code), and the front-end. All component need to be running.

Curio was tested on Windows 11 and MacOS Sonoma 14.5.   

**Python >= 3.9 & < 3.12 is needed.**

### Curio Backend

The backend source code is available on the `backend` folder. It is recommended to install its requirements on a virtual environment such as [Anaconda](https://anaconda.org). Inside the `backend` folder:

```console
pip install -r requirements.txt
```

Once requirements are installed we have to create a SQLite database for provenance.

```console
python create_provenance_db.py
```

Now the backend server can be started.

```console
python server.py
```

The backend is also responsible for user authentication. In order to use Curio's functionalities, you will need authentication. To do so, upgrade the database:

#### Apply migrations

You need to run this command before start using Curio:

```shell
# run this to apply any migration that hasn't run yet
FLASK_APP=server.py flask db upgrade
```

If the environment variable FLASK_APP does not work on the command above, set the environnment variable in your terminal. 

#### Create migration

```shell
# after updating any model, run this to generate a new migration
FLASK_APP=server.py flask db migrate -m "Migration Name"
```


### Python sandbox

Since modules on Curio can run Python code. It is necessary to run a Python sandbox. On `sandbox` folder.

To run without Docker (Anaconda environment recommended):

```console
pip install -r requirements.txt
```

Installing UTK's backend module to have access inside the sandbox:

```console
pip install utk-0.8.9.tar.gz
```

Run the server:

```console
python server.py
```

If you prefer to use Docker (can't use GPU for Ray Tracing):

```console
docker-compose up
```

### UTK workflow

Because Curio also uses UTK's frontend it is necessary to compile the UTK submodule. On `utk-workflow` folder:

```console
cd src/utk-ts
```

NodeJS is needed to build the frontend. Anaconda is recommended:

```console
npm install
npm run build 
```

### Curio frontend

To start Curio's frontend. Simply go `urban-workflows` and run:

```console
npm install
npm run build
npm run start
```

### Ray tracing

To use Ray Tracing from UTK's python module please consult UTK's [requirements](https://github.com/urban-toolkit/utk).

## First dataflow 

For a simple introductory example check [this](https://github.com/urban-toolkit/curio/blob/main/example1.md) tutorial.  

![Tutorial](https://github.com/urban-toolkit/curio/blob/main/images/final_result.png?raw=true)

## Team

Gustavo Moreira (UIC)   
[Maryam Hosseini](https://www.maryamhosseini.me/) (MIT)  
Carolina Veiga (UIUC)  
Lucas Alexandre (UFF)  
Nico Colaninno (Polimi)  
Leonardo Ferreira (UIC)  
[Daniel de Oliveira](http://www2.ic.uff.br/~danielcmo/) (UFF)  
[Nivan Ferreira](https://www.cin.ufpe.br/~nivan/) (UFPE)  
[Marcos Lage](http://www.ic.uff.br/~mlage/) (UFF)  
[Fabio Miranda](https://fmiranda.me) (UIC)  


## How to make contributions

If you're planning to contribute with Curio, please take a look at:

[Code guidelines](https://github.com/urban-toolkit/curio/blob/main/CODE_GUIDELINES.md)  
[How to fork](https://github.com/urban-toolkit/curio/blob/main/HOW_TO_FORK.md)  
[How to make pull requests](https://github.com/urban-toolkit/curio/blob/main/HOW_TO_MAKE_PULL_REQUESTS.md)  
[How to create issues](https://github.com/urban-toolkit/curio/blob/main/HOW_TO_CREATE_ISSUES.md)  