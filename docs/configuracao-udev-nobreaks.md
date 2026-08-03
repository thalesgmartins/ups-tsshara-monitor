# Configuração de Symlinks Estáveis para Nobreaks (udev rules)

Ao conectar múltiplos dispositivos seriais idênticos em sistemas Linux — uma situação muito comum tanto na infraestrutura de servidores quanto ao plugar múltiplos microcontroladores (como ESP8266, ESP32 ou Arduinos genéricos) —, o sistema operacional atribui portas como `/dev/ttyUSB0` e `/dev/ttyUSB1` por ordem de conexão.

Como os cabos dos nobreaks TS Shara utilizam o chip conversor CH340 (Vendor ID `1a86`, Product ID `7523`), eles não possuem um *Serial Number* único gravado no silício. A solução nativa e definitiva do Linux para fixar esses caminhos é mapear a **porta USB física** (a rota exata do hub na placa-mãe ou até mesmo nas portas de um Raspberry Pi/Orange Pi) usando regras do `udev`.

## Passo 1: Descobrir o mapeamento da porta (KERNELS)

Para que a regra funcione em diferentes dispositivos, precisamos identificar o endereço físico exato da porta em que o cabo está conectado no equipamento de destino.

1. Desconecte o cabo USB do nobreak do servidor ou gateway.
2. Reconecte **apenas** o cabo do nobreak que deseja mapear.
3. Imediatamente após conectar, execute o comando:
   ```bash
   dmesg | grep ttyUSB | tail -n 5
   ```
4. Procure na saída algo semelhante a:
   > `usb 1-1.3: ch341-uart converter now attached to ttyUSB1`

   Neste caso, o valor **`1-1.3`** é o identificador `KERNELS` da porta física. Anote este valor. Repita o processo para os demais nobreaks.

## Passo 2: Criar o arquivo de regras udev

No equipamento onde o nobreak vai ficar conectado de forma definitiva, crie (ou edite) o arquivo de regras no diretório do sistema:

```bash
sudo nano /etc/udev/rules.d/99-ups.rules
```

Adicione o conteúdo abaixo, substituindo os valores de `KERNELS` pelos que você encontrou no Passo 1:

```udev
# /etc/udev/rules.d/99-ups.rules
# Cria symlinks estaveis (/dev/TSSHARA0, /dev/TSSHARA1) para os nobreaks TS Shara

# Nobreak 1 -> /dev/TSSHARA0
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", KERNELS=="1-1.2", SYMLINK+="TSSHARA0"

# Nobreak 2 -> /dev/TSSHARA1
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", KERNELS=="1-1.3", SYMLINK+="TSSHARA1"
```
*Nota: Se o setup utilizar apenas um nobreak, mantenha somente a primeira linha configurada.*

## Passo 3: Aplicar e Validar as Regras

Para aplicar as novas regras sem precisar reiniciar o SO, basta recarregar o serviço `udev`:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Verifique se os symlinks foram criados corretamente listando o diretório `/dev`:

```bash
ls -l /dev/TSSHARA*
```
A saída deve mostrar os links simbólicos apontando para os respectivos *devices* dinâmicos, de forma parecida com isso:
`lrwxrwxrwx 1 root root 7 Ago 03 16:37 /dev/TSSHARA0 -> ttyUSB0`.

---

## Recursos para Aprofundamento (Deep Dive)

*   **Explorando a árvore de dispositivos:** Para criar regras avançadas ou investigar outros periféricos seriais (como gateways LoRa ou módems 4G em dispositivos ARM), utilize o comando `udevadm info -a -p $(udevadm info -q path -n /dev/ttyUSB0)`. Ele exibe todos os atributos do `sysfs` em forma de árvore, permitindo identificar variáveis além do Vendor/Product ID (como fabricantes de chips específicos).
*   **Documentação de referência do udev:** O [Arch Linux Wiki - udev](https://wiki.archlinux.org/title/Udev) é uma das fontes mais didáticas e pragmáticas sobre regras customizadas para manipulação de hardware no *user space*, abordando deste scripts de gatilho até permissões específicas (modo/group).
