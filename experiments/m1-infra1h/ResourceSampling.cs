namespace Sts2Headless;

internal static class ResourceSampling
{
    // The owner samples lifetime peak RSS at process close. Diagnostics opt in
    // to the original per-message OS query and its wire metadata.
    internal static readonly bool PerRequest =
        Environment.GetEnvironmentVariable("INFRA1H_REQUEST_RSS") == "1";
}
