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

1. Abra `Preparador_de_Logos.pyw` e clique em **① Abrir imagem**.
2. O app pergunta qual é a cor do fundo. Confirme a cor detectada nos cantos ou clique em **Escolher a cor** e depois no fundo da prévia original.
3. Escolha se quer manter a cor de fundo original ou substituí-la. Quando substituir, selecione fundo branco, transparente, preto ou uma cor personalizada.
4. Em **④ Ajuste as cores**, mantenha as cores encontradas ou clique em uma delas para uni-la a outra cor já detectada. Use os botões **−** e **+** para identificar de 2 a 12 cores.
5. Em **⑤ Qualidade das bordas**, ajuste a suavidade entre 1 e 3 apenas se necessário. O nível 2 é o padrão recomendado; 1 preserva mais detalhes e 3 suaviza mais as curvas.
6. Para logos com linhas muito estreitas, abra **⚙ Opções avançadas** e ative **Preservar detalhes finos**. Esse modo usa uma vetorização muito menos simplificada, preservando traços delicados sem o aspecto pixelado.
7. Confira a prévia e clique em **⑥ Salvar PNG**. O PNG terá até 2.000 px no maior lado.
8. Importe o PNG resultante no PE-Design Next para digitalizar o bordado.

Por exemplo, se a imagem contém rosa, verde-claro e verde-escuro, ao clicar no verde-claro as opções serão rosa e verde-escuro. Escolha verde-escuro para bordar a folha com uma única linha verde. A prévia mostra o resultado antes de salvar. Para a maior parte dos logos, remova o fundo e exporte com **fundo branco**. Transparência é útil quando o software de destino a interpreta corretamente.

## Requisitos

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
├── Preparador_de_Logos.pyw  # Interface Tkinter e pipeline de imagem
├── requirements.txt         # Dependências Python
└── README.md                # Documentação do projeto
```

## Como o processamento funciona

O pipeline principal está na função `process` em `Preparador_de_Logos.pyw`:

1. A imagem é carregada como RGBA; imagens acima de 4200 px no maior lado são reduzidas.
2. O fundo opcional é detectado pela mediana dos quatro cantos ou por uma cor amostrada na prévia.
3. Fundos coloridos são comparados em HSV; fundos neutros, em LAB. A remoção atua no canal alfa e pode ficar limitada às regiões conectadas à borda.
4. A imagem é suavizada levemente e seus pixels são agrupados em uma paleta de 2 a 12 cores, escolhida na interface.
5. Cada cor da paleta pode ser substituída por outra cor já detectada na imagem, permitindo unir tons semelhantes antes de bordar sem introduzir uma nova cor.
6. As regiões de cor são vetorizadas internamente, suavizadas conforme o nível escolhido e renderizadas novamente como PNG de até 2.000 px no maior lado.
7. Na exportação, a transparência é preservada ou composta sobre o fundo selecionado.

O app usa uma thread de trabalho para processar a imagem sem travar a interface. Alterações nos controles são agrupadas com um pequeno atraso antes de iniciar novo processamento.

## Limitações conhecidas

- A vetorização suaviza bordas serrilhadas, mas não recupera detalhes que não existiam na imagem original. Use o nível 1 quando detalhes pequenos forem importantes.
- Remoção por cor funciona melhor com fundos uniformes. Fotos, sombras, degradês e cores semelhantes às do logo podem exigir selecionar manualmente a cor do fundo na prévia.
- Ao alterar a quantidade de cores identificadas, a paleta é recalculada e as uniões de cores feitas anteriormente são desfeitas.
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
  python -c "import ast, pathlib; ast.parse(pathlib.Path('Preparador_de_Logos.pyw').read_text(encoding='utf-8'))"
  ```

## Licença

Ainda não há uma licença definida para o projeto. Adicione uma licença antes de aceitar ou distribuir contribuições de terceiros em condições específicas.
