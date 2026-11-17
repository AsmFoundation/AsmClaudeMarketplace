Local NuGet feed (see ../nuget.config).

Fill it with:

    dotnet pack Crc/Crc.asmproj -o packages

This file only keeps the folder in existence: restore can fail when a configured local
feed folder is missing, and the first `dotnet pack` restores before it creates `packages/`.
