"""Keep standard QtGui collection without unused PDF/virtual-keyboard plugins."""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Filter before PyInstaller walks plugin DLL dependencies. These two plugins
# otherwise bring QtPdf and QtQuick/QtQml into our Widgets-only application.
# Keep the stock hook's other plugins, translations, and hidden imports.
unused_plugins = {"qpdf.dll", "qtvirtualkeyboardplugin.dll"}
binaries = [
    (source, destination)
    for source, destination in binaries
    if Path(source).name.casefold() not in unused_plugins
]
