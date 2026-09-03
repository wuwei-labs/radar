// Safe, and split the way a real program splits: the accounts struct that
// declares the vault's seeds lives in `instructions/`, the code that signs with
// them lives in `state/`. Neither file can answer the question alone, which is
// the arrangement the rule's first pass exists for.
use anchor_lang::prelude::*;

pub mod instructions;
pub mod state;

use instructions::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod pda_sharing {
    use super::*;

    pub fn transfer_tokens(ctx: Context<TransferTokens>, amount: u64) -> Result<()> {
        instructions::transfer_tokens::handler(ctx, amount)
    }
}
