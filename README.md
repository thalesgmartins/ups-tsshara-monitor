# ups-tsshara-monitor

Monitoramento serial dos nobreaks **TS Shara UPS SYAL IN (4 a 12 kVA)** com publicação
via **MQTT** e **auto-discovery** para o **Home Assistant**.

O serviço lê os registradores do nobreak pela porta serial (protocolo **Modbus ASCII**
sobre o conversor USB↔Serial **CH340**), interpreta tensão, corrente, frequência, carga,
bateria, temperatura e a *status word*, e publica tudo em tópicos MQTT prontos para serem
descobertos automaticamente pelo Home Assistant.

---

## Sumário

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Pré-requisitos](#pré-requisitos)
- [Instalação para desenvolvimento (venv)](#instalação-para-desenvolvimento-venv)
- [Configuração das portas seriais (udev)](#configuração-das-portas-seriais-udev)
  - [Por que travar pela porta física](#por-que-travar-pela-porta-física)
  - [Passo 1 — Descobrir a porta física de cada nobreak](#passo-1--descobrir-a-porta-física-de-cada-nobreak)
  - [Passo 2 — Criar/atualizar a regra do udev](#passo-2--criaratualizar-a-regra-do-udev)
  - [Passo 3 — Aplicar as regras](#passo-3--aplicar-as-regras)
- [Execução com Docker](#execução-com-docker)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Integração com o Home Assistant](#integração-com-o-home-assistant)
- [Sensores publicados](#sensores-publicados)
- [Protocolo e ferramentas de diagnóstico](#protocolo-e-ferramentas-de-diagnóstico)
- [Solução de problemas](#solução-de-problemas)

---

## Visão geral

- Leitura periódica dos registradores do nobreak via **Modbus ASCII** (função `0x03`).
- Publicação em **MQTT** com *retain* e **LWT** (Last Will) para sinalizar `online`/`offline`.
- **Auto-discovery** do Home Assistant: os sensores aparecem sozinhos, agrupados por
  dispositivo (`Nobreak <SERVER_NAME>`).
- **Trava de software** para status flutuante: força os estados de falta de rede
  (`utility_fail`) e bateria baixa (`battery_low`) com base nos valores reais de tensão de
  entrada e carga da bateria, evitando "piscar" de status do firmware.
- Projeto multi-instância: **um container por nobreak**.

---

## Arquitetura

O pacote `ups_tsshara_monitor` sobe **duas threads** que compartilham um estado em memória
protegido por *lock*:

| Módulo         | Responsabilidade |
|----------------|------------------|
| `__main__.py`  | Ponto de entrada. Inicia as threads de *polling* e MQTT e mantém o processo vivo. Aceita `--debug`. |
| `poller.py`    | Abre a serial (8N1, DTR/RTS ativos), lê os blocos de registradores em laço e aplica as travas de software de status. |
| `modbus.py`    | Monta e interpreta frames Modbus ASCII (LRC, `build_request`, `parse_response`). |
| `registers.py` | Mapa de registradores (`REG_MAP`), bits de status (`STATUS_BITS`) e definição dos sensores MQTT (`MQTT_SENSORS`). |
| `mqtt.py`      | Conecta ao broker, publica o *discovery*, a disponibilidade e o estado dos sensores; calcula o status textual (`Online`, `Charging`, `On Battery`, `Low Battery`). |
| `config.py`    | Lê todas as configurações a partir de variáveis de ambiente. |

Fluxo resumido:

```
Nobreak ──USB/CH340──> /dev/ttyUSB* ──(udev)──> /dev/TSSHARA0/1
                                                     │
                                          (Docker mapeia device)
                                                     ▼
                                     container: /dev/ttyTSSHARA0
                                                     │
                              poller (Modbus ASCII) → estado compartilhado → mqtt → broker → Home Assistant
```

---

## Pré-requisitos

- Nobreak **TS Shara UPS SYAL IN** com saída serial e cabo/conversor **CH340**
  (Vendor ID `1a86`, Product ID `7523`).
- Host Linux (validado em **Raspberry Pi**) com Docker e Docker Compose.
- Um broker **MQTT** acessível (ex.: Mosquitto) — normalmente o mesmo do Home Assistant.

> Para instalar o Docker rapidamente, há um utilitário no repositório:
>
> ```bash
> ./scripts/install-docker.sh
> ```

---

## Instalação para desenvolvimento (venv)

Para desenvolver/depurar localmente, sem Docker:

```bash
# Cria um novo ambiente virtual do Python
python -m venv .venv

# Ativa o ambiente virtual
source .venv/bin/activate

# Instala o projeto em modo editável
pip install -e .
```

Depois disso o monitor pode ser executado de duas formas:

```bash
# Executando o módulo diretamente
python3 -m ups_tsshara_monitor

# Executando o script instalado
ups

# Log verboso
ups --debug
```

Se `MQTT_HOST` não estiver definido, a thread MQTT dorme e o serviço roda apenas em
**modo leitura da serial** — útil para validar a comunicação com o nobreak.

---

## Configuração das portas seriais (udev)

Esta é a etapa mais importante quando há **mais de um nobreak** conectado ao mesmo host.

### Por que travar pela porta física

O Vendor ID `1a86` e o Product ID `7523` pertencem ao chip **CH340**, um conversor
USB↔Serial muito comum. Como **todos os cabos têm exatamente o mesmo par Vendor/Product**,
não dá para diferenciá-los por esses IDs. Se a regra do udev não amarrar cada nobreak à sua
**porta USB física**, a cada reboot o Linux sorteia aleatoriamente quem vira `TSSHARA0` e
quem vira `TSSHARA1` — e os containers passam a monitorar o nobreak errado.

A solução é usar o parâmetro `KERNELS=="1-1.X"`, onde `1-1.X` identifica a porta física
onde o cabo está espetado. Assim o mapeamento fica estável entre reinicializações.

### Passo 1 — Descobrir a porta física de cada nobreak

Para não errar, **desconecte e reconecte apenas o cabo USB** do nobreak em questão e, logo
em seguida, rode:

```bash
dmesg | grep ttyUSB | tail -n 5
```

Procure a linha de anexação da porta `tty`, algo como:

```
usb 1-1.3: ch341-uart converter now attached to ttyUSB1
```

O trecho `1-1.3` (pode ser `1-1.2`, `1-1.4`, etc., dependendo da porta física usada) é o
valor que vai em `KERNELS`. Repita o processo para cada nobreak, anotando a porta de cada um.

### Passo 2 — Criar/atualizar a regra do udev

Abra (ou crie) o arquivo de regras:

```bash
sudo nano /etc/udev/rules.d/99-ups.rules
```

Deixe o conteúdo com **uma linha por nobreak**. Substitua os valores de `KERNELS` pelos que
você descobriu no Passo 1:

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", KERNELS=="1-1.2", SYMLINK+="TSSHARA0"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", KERNELS=="1-1.3", SYMLINK+="TSSHARA1"
```

- `SYMLINK+="TSSHARA0"` cria o atalho fixo `/dev/TSSHARA0` para o **nobreak 1**.
- `SYMLINK+="TSSHARA1"` cria o atalho fixo `/dev/TSSHARA1` para o **nobreak 2**.

Salve com `Ctrl+O`, `Enter` e saia com `Ctrl+X`.

> Se você tiver **apenas um nobreak**, basta a primeira linha (`TSSHARA0`).

### Passo 3 — Aplicar as regras

Recarregue as regras e dispare a criação dos atalhos sem precisar reiniciar:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Confirme se os *symlinks* apareceram:

```bash
ls -l /dev/TSSHARA*
```

Cada `TSSHARA*` deve aparecer apontando para o `ttyUSB` correspondente, por exemplo:

```
/dev/TSSHARA0 -> ttyUSB0
/dev/TSSHARA1 -> ttyUSB1
```

---

## Execução com Docker

O `docker-compose.yml` sobe **um container por nobreak**. Cada serviço mapeia o *symlink*
estável do host (`/dev/TSSHARA0`, `/dev/TSSHARA1`) para o caminho **fixo dentro do
container** `/dev/ttyTSSHARA0`. Isso permite que **todos os containers usem o mesmo
`SERIAL_PORT` padrão** (`/dev/ttyTSSHARA0`), sem precisar reconfigurar a porta por container.

```yaml
services:
  # Nobreak 1
  ups-monitor-nb-01:
    build: .
    container_name: ups_monitor_nb_01
    devices:
      - /dev/TSSHARA0:/dev/ttyTSSHARA0
    env_file: "NB-01.env"
    restart: unless-stopped

  # Nobreak 2
  ups-monitor-nb-02:
    build: .
    container_name: ups_monitor_nb_02
    devices:
      - /dev/TSSHARA1:/dev/ttyTSSHARA0
    env_file: "NB-02.env"
    restart: unless-stopped
```

Cada container tem seu próprio arquivo de ambiente (`NB-01.env`, `NB-02.env`) com um
`SERVER_NAME` diferente, para que apareçam como dispositivos separados no Home Assistant.

Suba os serviços:

```bash
docker compose up -d
```

Acompanhe os logs:

```bash
docker compose logs -f ups-monitor-nb-01
```

> **Alternativa:** se preferir manter o mesmo nome de device dentro do container
> (`/dev/TSSHARA0:/dev/TSSHARA0`), defina `SERIAL_PORT=/dev/TSSHARA0` (ou `.../TSSHARA1`)
> no `.env` de cada container. A abordagem padrão acima evita isso mapeando sempre para
> `/dev/ttyTSSHARA0`.

Os arquivos `docker-compose.yml` e `*.env` estão no `.gitignore` (não devem ser commitados).
Use o `docker-compose.yml.example` como base.

---

## Variáveis de ambiente

Todas as configurações vêm de variáveis de ambiente (lidas em `config.py`):

| Variável            | Padrão                   | Descrição |
|---------------------|--------------------------|-----------|
| `SERVER_NAME`       | `ups_tsshara_monitor`    | Identificador da instância. Compõe o tópico MQTT e o nome do dispositivo no HA. **Use um valor único por container.** |
| `MQTT_HOST`         | *(vazio)*                | Host do broker MQTT. Se vazio, roda só em modo leitura da serial. |
| `MQTT_PORT`         | `1883`                   | Porta do broker MQTT. |
| `MQTT_USER`         | *(vazio)*                | Usuário do broker (opcional). |
| `MQTT_PASS`         | *(vazio)*                | Senha do broker (opcional). |
| `MQTT_PREFIX`       | `homeassistant/sensor`   | Prefixo do tópico de discovery. |
| `SERIAL_PORT`       | `/dev/ttyTSSHARA0`       | Porta serial dentro do container. |
| `SERIAL_BAUD`       | `9600`                   | Baud rate. |
| `SERIAL_SLAVE_ID`   | `1`                      | ID do escravo Modbus. |
| `SERIAL_POLL_SECS`  | `5`                      | Intervalo de leitura, em segundos. |

O tópico base é montado como `MQTT_PREFIX/SERVER_NAME`
(ex.: `homeassistant/sensor/ups_monitor_nb_01`).

Exemplo de arquivo de ambiente (`NB-01.env`):

```env
# Identificação
SERVER_NAME=ups_monitor_nb_01

# MQTT
MQTT_HOST=192.168.0.10
MQTT_PORT=1883
MQTT_USER=usuario
MQTT_PASS=senha

# Serial
SERIAL_POLL_SECS=5
```

---

## Integração com o Home Assistant

Ao conectar ao broker, o serviço:

1. Publica **disponibilidade** em `.../availability` (`online`/`offline`), com LWT para
   marcar `offline` automaticamente se o processo cair.
2. Publica a **configuração de discovery** de cada sensor (com `expire_after` de 120s), de
   modo que o Home Assistant crie as entidades sozinho, agrupadas sob o dispositivo
   `Nobreak <SERVER_NAME>` (fabricante *Tsshara*, modelo *SYAL IN*).
3. Publica o **estado** de cada sensor a cada ciclo de leitura.

Além dos sensores numéricos, há um sensor textual **UPS Status** com os valores:

| Status        | Condição |
|---------------|----------|
| `Online`      | Rede OK e bateria em 100%. |
| `Charging`    | Rede OK, bateria ainda carregando (< 100%). |
| `On Battery`  | Falta de rede (`utility_fail`). |
| `Low Battery` | Falta de rede **e** bateria baixa (`battery_low`). |

---

## Sensores publicados

| Campo               | Sensor              | Unidade | Device class   |
|---------------------|---------------------|---------|----------------|
| `input_voltage`     | Tensão Entrada      | V       | voltage        |
| `input_current`     | Corrente Entrada    | A       | current        |
| `input_frequency`   | Frequência Entrada  | Hz      | frequency      |
| `input_pf`          | FP Entrada          | —       | power_factor   |
| `output_voltage`    | Tensão Saída        | V       | voltage        |
| `output_current`    | Corrente Saída      | A       | current        |
| `output_frequency`  | Frequência Saída    | Hz      | frequency      |
| `output_pf`         | FP Saída            | —       | power_factor   |
| `output_load`       | Carga               | %       | power_factor   |
| `output_power`      | Potência Ativa      | kW      | power          |
| `output_apparent`   | Potência Aparente   | kVA     | —              |
| `battery_charge`    | Bateria             | %       | battery        |
| `battery_voltage`   | Tensão Bateria (DC) | V       | voltage        |
| `temperature`       | Temperatura         | °C      | temperature    |
| `bypass_voltage`    | Tensão Bypass       | V       | voltage        |
| `bypass_frequency`  | Frequência Bypass   | Hz      | frequency      |

Bits da *status word* decodificados: `utility_fail`, `battery_low`, `bypass_active`,
`ups_fault`, `ups_standby`, `test_in_progress`, `shutdown_active`, `beeper_on`.

---

## Protocolo e ferramentas de diagnóstico

A comunicação é **Modbus ASCII** a 9600 8N1, lendo blocos de *holding registers* (função
`0x03`). Cada frame é validado por **LRC**; alguns firmwares enviam LRC incorreto, então o
parser registra o aviso mas segue processando.

Para inspecionar o protocolo há um script auxiliar:

```bash
# Escuta passiva enquanto o software oficial (UPS Power MTR) está lendo
python3 scripts/protocol_sniffer.py --sniff

# Varre os registradores 0x0000–0x00FF (rodar SEM o software oficial aberto)
python3 scripts/protocol_sniffer.py --scan

# Dump hexadecimal bruto
python3 scripts/protocol_sniffer.py --raw
```

---

## Solução de problemas

**`Error: ... no such file or directory` ao subir o container**
O device apontado no `docker-compose.yml` não existe no host. Isso costuma acontecer quando
a seção `devices` ainda aponta para um caminho antigo (ex.: `/dev/ups_servidores`) ou quando
o *symlink* do udev não foi criado. Confirme:

1. Que os *symlinks* existem: `ls -l /dev/TSSHARA*`.
2. Que a seção `devices` de cada container aponta para o *symlink* correto
   (`/dev/TSSHARA0` para o nobreak 1, `/dev/TSSHARA1` para o nobreak 2).
3. Rode `docker compose up -d` novamente.

**Os dois nobreaks trocam de identidade após reboot**
A regra do udev não está amarrando pela porta física. Revise o `KERNELS=="1-1.X"` de cada
linha (veja [Configuração das portas seriais](#configuração-das-portas-seriais-udev)).

**`Sem resposta no bloco ...` nos logs**
Verifique cabo/porta, o `SERIAL_SLAVE_ID` e se o software oficial do nobreak não está aberto
segurando a serial.

**MQTT não conecta**
Confirme `MQTT_HOST`, `MQTT_PORT`, credenciais e alcance de rede a partir do container.
