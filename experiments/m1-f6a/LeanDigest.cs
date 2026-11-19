using System.Buffers;
using System.Security.Cryptography;
using System.Text;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private static string HashDigest(string text)
    {
        int capacity = Encoding.UTF8.GetByteCount(text);
        byte[] bytes = ArrayPool<byte>.Shared.Rent(capacity);
        try
        {
            int count = Encoding.UTF8.GetBytes(text.AsSpan(), bytes);
            Span<byte> digest = stackalloc byte[32];
            SHA256.HashData(bytes.AsSpan(0, count), digest);
            return Convert.ToHexStringLower(digest);
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(bytes);
        }
    }
}
