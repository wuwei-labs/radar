use anchor_lang::prelude::*;
use anchor_spl::token::{self, Transfer};

pub const VAULT_SEED: &[u8] = b"vault";

#[account]
pub struct Vault {
    pub user: Pubkey,
    pub bump: u8,
}

impl Vault {
    /// Signs a transfer out of the vault it is stored in.
    ///
    /// This file contains no accounts struct at all, so nothing here says which
    /// account `VAULT_SEED` derives — that is declared one file over, in
    /// `instructions/transfer_tokens.rs`. Read on its own the signer looks like
    /// a PDA reused across domains; read together with the declaration it is the
    /// vault signing for itself.
    pub fn transfer_out<'info>(
        &self,
        authority: AccountInfo<'info>,
        from: AccountInfo<'info>,
        to: AccountInfo<'info>,
        token_program: AccountInfo<'info>,
        amount: u64,
    ) -> Result<()> {
        let user = self.user;
        let seeds = &[VAULT_SEED, user.as_ref(), &[self.bump]];
        let signer = &[&seeds[..]];

        let cpi_accounts = Transfer {
            from,
            to,
            authority,
        };
        let cpi_ctx = CpiContext::new_with_signer(token_program, cpi_accounts, signer);
        token::transfer(cpi_ctx, amount)
    }
}
