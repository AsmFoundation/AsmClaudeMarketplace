using System.Runtime.InteropServices;

// libcalc.so is a Linux x86-64 ELF library: the app builds everywhere but runs on Linux x64 only.
if (!OperatingSystem.IsLinux() || RuntimeInformation.ProcessArchitecture != Architecture.X64)
{
    Console.Error.WriteLine("libcalc.so is a Linux x86-64 library: run this app on Linux x64 (WSL, a container or CI).");
    return 1;
}

long[] values = [1, 2, 3, 4];
Console.WriteLine(Native.CalcSum(values, values.Length));
return 0;

internal static partial class Native
{
    /// <summary>int64_t calc_sum(const int64_t *values, int64_t count), exported by libcalc.so.</summary>
    [LibraryImport("calc", EntryPoint = "calc_sum")]
    internal static partial long CalcSum(ReadOnlySpan<long> values, long count);
}
