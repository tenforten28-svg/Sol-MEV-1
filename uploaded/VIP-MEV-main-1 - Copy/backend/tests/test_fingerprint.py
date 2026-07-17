"""
Tests for Fingerprinting
========================
Validates route fingerprint creation and stability.
"""

import pytest
from bot.alpha import (
    build_fingerprint,
    build_fingerprint_from_opportunity,
    fingerprint_hash,
    parse_fingerprint,
    mint_to_symbol
)


class TestFingerprintBuilder:
    """Test fingerprint building"""
    
    def test_build_basic_fingerprint(self):
        """Test basic fingerprint creation"""
        fp = build_fingerprint(
            dex_programs=["RAYDIUM", "ORCA"],
            pool_accounts=["58oQChx4", "HJPjoWUr"],
            token_path=["USDC", "SOL", "USDC"],
            cu_bucket="CU_200_250"
        )
        
        assert "ORCA|RAYDIUM" in fp or "RAYDIUM|ORCA" in fp  # Should be sorted
        assert "USDC->SOL->USDC" in fp
        assert "pools:" in fp
        assert "cu:CU_200_250" in fp
    
    def test_fingerprint_order_independence(self):
        """Test that order of inputs doesn't change fingerprint"""
        fp1 = build_fingerprint(
            dex_programs=["RAYDIUM", "ORCA"],
            pool_accounts=["58oQChx4", "HJPjoWUr"],
            token_path=["USDC", "SOL", "USDC"],
        )
        
        fp2 = build_fingerprint(
            dex_programs=["ORCA", "RAYDIUM"],  # Different order
            pool_accounts=["HJPjoWUr", "58oQChx4"],  # Different order
            token_path=["USDC", "SOL", "USDC"],
        )
        
        assert fp1 == fp2, "Fingerprints should be identical regardless of input order"
    
    def test_different_pools_different_fingerprint(self):
        """Test that different pools produce different fingerprints"""
        fp1 = build_fingerprint(
            dex_programs=["RAYDIUM", "ORCA"],
            pool_accounts=["POOL_A", "POOL_B"],
            token_path=["USDC", "SOL", "USDC"],
        )
        
        fp2 = build_fingerprint(
            dex_programs=["RAYDIUM", "ORCA"],
            pool_accounts=["POOL_C", "POOL_D"],  # Different pools
            token_path=["USDC", "SOL", "USDC"],
        )
        
        assert fp1 != fp2, "Different pools should produce different fingerprints"
    
    def test_different_tokens_different_fingerprint(self):
        """Test that different token paths produce different fingerprints"""
        fp1 = build_fingerprint(
            dex_programs=["RAYDIUM"],
            pool_accounts=["POOL_A"],
            token_path=["USDC", "SOL", "USDC"],
        )
        
        fp2 = build_fingerprint(
            dex_programs=["RAYDIUM"],
            pool_accounts=["POOL_A"],
            token_path=["USDC", "BONK", "USDC"],  # Different token path
        )
        
        assert fp1 != fp2, "Different token paths should produce different fingerprints"
    
    def test_cu_bucket_affects_fingerprint(self):
        """Test that CU bucket is included when provided"""
        fp1 = build_fingerprint(
            dex_programs=["RAYDIUM"],
            pool_accounts=["POOL_A"],
            token_path=["USDC", "SOL", "USDC"],
            cu_bucket="CU_100_150"
        )
        
        fp2 = build_fingerprint(
            dex_programs=["RAYDIUM"],
            pool_accounts=["POOL_A"],
            token_path=["USDC", "SOL", "USDC"],
            cu_bucket="CU_200_250"  # Different CU bucket
        )
        
        assert fp1 != fp2, "Different CU buckets should produce different fingerprints"


class TestFingerprintFromOpportunity:
    """Test building fingerprint from opportunity details"""
    
    def test_build_from_opportunity(self):
        """Test building fingerprint from opportunity parameters"""
        fp = build_fingerprint_from_opportunity(
            buy_pool="58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            sell_pool="HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
            buy_dex="raydium",
            sell_dex="orca",
            buy_mint="So11111111111111111111111111111111111111112",
            sell_mint="So11111111111111111111111111111111111111112",
            quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )
        
        assert fp is not None
        assert "RAYDIUM" in fp or "raydium" in fp.lower()
        assert "ORCA" in fp or "orca" in fp.lower()


class TestFingerprintParsing:
    """Test fingerprint parsing"""
    
    def test_parse_fingerprint(self):
        """Test parsing a fingerprint back to components"""
        fp = "ORCA|RAYDIUM::USDC->SOL->USDC::pools:58oQChx4,HJPjoWUr::cu:CU_200_250"
        
        parsed = parse_fingerprint(fp)
        
        assert "ORCA" in parsed['dexs']
        assert "RAYDIUM" in parsed['dexs']
        assert parsed['token_path'] == ["USDC", "SOL", "USDC"]
        assert len(parsed['pools']) == 2
        assert parsed['cu_bucket'] == "CU_200_250"
    
    def test_fingerprint_hash(self):
        """Test fingerprint hashing for storage"""
        fp = "ORCA|RAYDIUM::USDC->SOL->USDC::pools:58oQChx4,HJPjoWUr"
        
        hash1 = fingerprint_hash(fp)
        hash2 = fingerprint_hash(fp)
        
        assert hash1 == hash2, "Same fingerprint should produce same hash"
        assert len(hash1) == 12, "Hash should be 12 characters"


class TestMintToSymbol:
    """Test mint address to symbol conversion"""
    
    def test_known_mints(self):
        """Test conversion of known mint addresses"""
        assert mint_to_symbol("So11111111111111111111111111111111111111112") == "SOL"
        assert mint_to_symbol("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") == "USDC"
        assert mint_to_symbol("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263") == "BONK"
    
    def test_unknown_mint(self):
        """Test that unknown mints return first 8 chars"""
        result = mint_to_symbol("UnknownMintAddress12345678901234567890")
        assert result == "UnknownM"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
