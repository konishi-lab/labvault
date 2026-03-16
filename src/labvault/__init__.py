"""labvault — Lab data management SDK.

Auto-logs notebook execution, stores data with LLM-friendly metadata,
and enables AI-powered analysis.

Usage:
    from labvault import Lab

    lab = Lab("konishi-lab")
    exp = lab.new("XRD measurement", sample="Fe-10Cr alloy #42")
    exp.add("~/Desktop/xrd_data.ras")
"""

__version__ = "0.1.0"
