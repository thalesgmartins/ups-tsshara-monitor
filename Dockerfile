# _____ _____   _____ _                      ___  ___            _ _             
#|_   _/  ___| /  ___| |                     |  \/  |           (_) |            
#  | | \ `--.  \ `--.| |__   __ _ _ __ __ _  | .  . | ___  _ __  _| |_ ___  _ __ 
#  | |  `--. \  `--. \ '_ \ / _` | '__/ _` | | |\/| |/ _ \| '_ \| | __/ _ \| '__|
#  | | /\__/ / /\__/ / | | | (_| | | | (_| | | |  | | (_) | | | | | || (_) | |   
#  \_/ \____/  \____/|_| |_|\__,_|_|  \__,_| \_|  |_/\___/|_| |_|_|\__\___/|_|   
#                                                                                
                                                                                
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copia arquivos de definição
COPY pyproject.toml README.md ./

# Copia o fonte
COPY ups_tsshara_monitor/ ./ups_tsshara_monitor/

# Instala o projeto e dependências
RUN pip install --no-cache-dir .

# Copia as configurações
#COPY config/ ./config/

# Comando para iniciar o Monitor
ENTRYPOINT ["python", "-m", "ups_tsshara_monitor"]

# Parâmetros que serão passados ao script
CMD ["--mqtt"]