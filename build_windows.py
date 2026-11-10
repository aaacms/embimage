"""Gera o pacote portátil do EmbImage para Windows de 64 bits."""
import os
from pathlib import Path
import struct
import sys
import zipfile


def main():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise SystemExit('Execute com Python de 64 bits no Windows.')

    root = Path(__file__).resolve().parent
    build = root / 'build'
    dist = root / 'dist'
    os.environ['PYINSTALLER_CONFIG_DIR'] = str(build / 'cache')
    from PyInstaller.__main__ import run
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info

    if not tcltk_info.available:
        raise SystemExit('O Tkinter precisa estar funcional para gerar o pacote Windows.')

    run([
        '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'EmbImage',
        '--distpath', str(dist), '--workpath', str(build / 'work'),
        '--specpath', str(build), '--paths', str(root),
        '--hidden-import', 'vtracer.vtracer',
        '--hidden-import', 'resvg_py.resvg_py',
        str(root / 'Preparador_de_Logos.pyw'),
    ])

    package = dist / 'EmbImage'
    (package / 'LEIA-ME.txt').write_text(
        'EmbImage - Preparador de logos\n\n'
        '1. Copie o ZIP para o computador em que vai usar o aplicativo.\n'
        '2. Clique com o botao direito no ZIP e escolha Extrair tudo.\n'
        '3. Abra a pasta extraida e de dois cliques em EmbImage.exe.\n\n'
        'Nao precisa instalar Python nem usar a internet.\n'
        'Mantenha a pasta _internal junto de EmbImage.exe.\n'
        'Para criar um atalho, clique com o botao direito em EmbImage.exe,\n'
        'escolha Mostrar mais opcoes > Enviar para > Area de trabalho.\n\n'
        'Pacote para Windows 10/11 de 64 bits.\n'
        'Siga os numeros de 1 a 6 no aplicativo para preparar e salvar a imagem.\n',
        encoding='utf-8',
    )
    archive = dist / 'EmbImage-Windows.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                output.write(path, path.relative_to(dist))
    print(f'Pacote pronto: {archive}')


if __name__ == '__main__':
    main()
