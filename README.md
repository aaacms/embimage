# EmbImage — Preparador de Logos para Bordado

Aplicação desktop em Python para preparar imagens raster antes da digitalização no **PE-Design Next**. Ela recebe imagens comuns, limpa ou troca o fundo, identifica as cores principais e exporta um PNG mais adequado para ser convertido em matriz de bordado.

> Escopo: este projeto prepara a arte de entrada. Ele **não** gera arquivos de bordado (`.pes`, `.dst` etc.) nem substitui a digitalização feita no PE-Design Next.

## Problema que resolve

Imagens usadas como referência para bordado frequentemente vêm em JPG, PNG ou WEBP, com fundo, pouca resolução, sombras e cores em excesso. Esses elementos dificultam a vetorização/digitalização e podem criar pontos, trocas de linha ou áreas indesejadas.

O EmbImage oferece um fluxo visual simples para:

- abrir `PNG`, `JPG/JPEG`, `WEBP` e `BMP`;
- remover um fundo de cor uniforme automaticamente ou a partir de uma cor escolhida pelo usuário;
- identificar de 2 a 12 cores predominantes, em quantidade escolhida pela pessoa usuária, e permitir que ela una cores semelhantes;
- transformar as áreas de cor em curvas suaves e gerar um PNG de até 2.000 px no maior lado;
- compor o resultado sobre fundo branco, preto, personalizado ou transparente;
- exportar PNG para importar no PE-Design Next.

## Uso para a pessoa usuária

Siga os números na lateral do aplicativo:

1. **Abrir imagem:** selecione o logo.
2. **Cor do fundo:** a cor é detectada automaticamente; use **Escolher na imagem** se precisar corrigir.
3. **Fundo final:** mantenha o original ou escolha branco, transparente, preto ou outra cor.
4. **Cores:** ajuste a quantidade com **− / +**. Clique em uma amostra para uni-la a outra cor.
5. **Bordas:** ajuste de 1 (mais detalhes) a 3 (mais suave). Em **Opções avançadas** ficam apenas os ajustes anteriores de detalhes finos e remoção em áreas internas.
6. **Salvar PNG:** confira original e resultado e escolha onde salvar.

A seleção de fundo só funciona após ativar **Escolher na imagem**; o mesmo botão cancela a seleção. O salvamento aguarda a atualização do resultado. O PNG pode ser importado no PE-Design Next.

Atalhos: Ctrl+O para abrir, Ctrl+S para salvar e Ctrl+Z para desfazer um ajuste.

## Usar em outro computador (sem Python)

O pacote portátil está em `dist/EmbImage-Windows.zip`. Copie esse ZIP para o outro computador, clique com o botão direito e escolha **Extrair tudo**. Abra a pasta extraída e dê dois cliques em **EmbImage.exe**.

Mantenha a pasta `_internal` junto do executável. Não é necessário instalar Python, ter internet ou abrir um terminal. O pacote é destinado ao Windows 10/11 de 64 bits.

Para gerar novamente o pacote, neste projeto e com Python de 64 bits no Windows:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe build_windows.py
```

O empacotamento usa [PyInstaller](https://www.pyinstaller.org/en/stable/operating-mode.html). As dependências ficam dentro do pacote; os arquivos pessoais usados nos testes não são incluídos.

## Requisitos para executar pelo código-fonte

- Windows (a interface usa Tkinter e o arquivo de entrada é `.pyw`)
- Python 3.10 ou mais recente
- Pillow, NumPy e OpenCV
- VTracer (vetorização interna) e resvg-py (renderização do PNG final)

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

Execute a interface:

```powershell
python Preparador_de_Logos.pyw
```

Também é possível dar duplo clique em `Preparador_de_Logos.pyw` depois que o Python estiver associado a arquivos `.pyw`.

## Interface de linha de comando

Há um modo rápido, principalmente útil para testes e automação:

```powershell
python Preparador_de_Logos.pyw --demo entrada.jpg --out resultado.png
```

Esse modo detecta a paleta predominante, remove automaticamente a cor dos cantos, usa suavidade de bordas nível 2 e gera um PNG de até 2.000 px no maior lado. Ele não aplica substituições manuais de cores.

## Estrutura

```text
.
├── Preparador_de_Logos.pyw  # Ponto de entrada e processamento de imagem
├── embimage_ui.py           # Interface Tkinter e coordenação das tarefas
├── tests/                  # Regressões do fluxo de edição e layout
├── requirements.txt        # Dependências Python
└── README.md               # Documentação do projeto
```

## Como o processamento funciona

O pipeline principal está na função `process` em `Preparador_de_Logos.pyw`:

1. A imagem é carregada como RGBA; imagens acima de 4200 px no maior lado são reduzidas.
2. O fundo opcional é detectado pela mediana dos quatro cantos ou por uma cor amostrada na prévia.
3. Antes de reduzir as cores, a imagem é redimensionada para até 2.000 px no maior lado, preservando as bordas intermediárias. No JPEG, a máscara de fundo é calculada antes da ampliação, para não destacar blocos de compressão. Fundos coloridos são comparados em HSV; fundos neutros, em LAB. A remoção atua no canal alfa e pode ficar limitada às regiões conectadas à borda.
4. A imagem é suavizada levemente e seus pixels são agrupados em uma paleta de 2 a 12 cores, escolhida na interface. A redução de cores e o traçado já ocorrem na resolução final, evitando ampliar degraus criados na imagem pequena.
5. Cada cor da paleta pode ser substituída por outra cor já detectada na imagem, permitindo unir tons semelhantes antes de bordar sem introduzir uma nova cor.
6. As regiões de cor são vetorizadas internamente com tolerância de curvas de 0,3 / 0,6 / 1 pixel da saída nos níveis 1 / 2 / 3 para PNG. No JPEG, a máscara e a tolerância são suavizadas conforme a escala da ampliação para reduzir serrilhados da compressão. Em artes neutras sobre fundo colorido, a separação considera a cromaticidade para não seguir os blocos do JPEG. Fragmentos novos e isolados são comparados aos componentes da origem antes de serem descartados; pontos e acentos originais são preservados. **Preservar detalhes finos** desativa essa limpeza adicional.
7. Na exportação, a transparência é preservada ou composta sobre o fundo selecionado.

Onde o traçado altera componentes muito finos, o app recupera a cobertura parcial da imagem de entrada e aplica as uniões de cores. Em fundos coloridos, essa recuperação respeita a máscara de fundo para não ressuscitar resíduos. Transparências existentes não se tornam opacas.

O app usa uma única thread de trabalho por vez, inclusive para identificar cores, sem executar operações do Tkinter nessa thread. Alterações nos controles são agrupadas com um pequeno atraso. Resultados de ajustes ou imagens anteriores são descartados; o salvamento só é liberado quando a prévia corresponde aos ajustes atuais.

## Limitações conhecidas

- A vetorização suaviza bordas serrilhadas, mas não recupera detalhes que não existiam na imagem original. Traços menores que um pixel podem continuar suaves, para não inventar espessuras. Use **Bordas 1** quando detalhes pequenos forem importantes.
- Remoção por cor funciona melhor com fundos uniformes. Fotos, sombras, degradês e cores semelhantes às do logo podem exigir selecionar manualmente a cor do fundo na prévia.
- Ao alterar a quantidade de cores identificadas ou a remoção de fundo, a paleta é recalculada e as uniões anteriores são desfeitas. Use `Ctrl+Z` para recuperar o ajuste anterior e suas uniões.
- A qualidade final do bordado ainda depende da digitalização, do tamanho físico, do tecido, da estabilização e das configurações de pontos escolhidas no PE-Design Next.

## Orientações para contribuidores e assistentes de IA

- Preserve o objetivo de **preparar imagens para bordado**, não implementar um editor gráfico genérico nem um digitalizador de matrizes.
- A interface é destinada também a pessoas leigas: mantenha linguagem em português simples, ações visíveis e um fluxo curto.
- A edição de cores deve continuar explícita e reversível na sessão: a pessoa decide quais tons serão unidos; cada cor só pode ser trocada por outra cor detectada na mesma imagem.
- Não remova os formatos de entrada atuais nem altere o PNG como formato de saída padrão sem uma razão compatível com PE-Design Next.
- O processamento deve permanecer responsivo: tarefas pesadas não devem executar na thread da interface Tkinter.
- A vetorização é interna; a saída pública do aplicativo deve continuar sendo PNG, mesmo que um SVG temporário seja usado em memória durante o processamento.
- Alterações em remoção de fundo devem considerar falsos positivos: partes do logo com a mesma cor do fundo não podem ser apagadas sem uma opção explícita.
- Ao adicionar dependências, atualize `requirements.txt` e esta documentação.
- Antes de enviar uma alteração, valide ao menos a sintaxe com:

  ```powershell
  python -c "import ast, pathlib; [ast.parse(path.read_text(encoding='utf-8')) for path in (pathlib.Path('Preparador_de_Logos.pyw'), pathlib.Path('embimage_ui.py'))]"
  ```

- Para validar o processamento real, as exportações e os estados da interface (requer Tkinter disponível):

  ```powershell
  python -m unittest discover -s tests -v
  ```

- `tests/test_image_quality.py` compara uma referência com letras serifadas e linhas finas com sua versão reduzida. Verifica a geometria das letras, a cobertura parcial dos traços, as uniões de cores e a transparência, incluindo bordas no nível 3.
- `tests/test_jpeg_quality.py` verifica resíduos de fundos coloridos, detalhes internos protegidos e a preservação de pontos e linhas legítimos em imagens JPEG.

## Licença

Ainda não há uma licença definida para o projeto. Adicione uma licença antes de aceitar ou distribuir contribuições de terceiros em condições específicas.
