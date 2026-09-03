use anchor_lang::prelude::*;

#[account]
pub struct Data {
    pub value: u64,
}

impl Data {
    /// VULN: writes unconditionally. Same name and same position as the safe
    /// variant's guard, so the two mocks differ only in whether anything here
    /// refuses to run on an account that already holds state.
    pub fn init(&mut self, value: u64) -> Result<()> {
        self.value = value;
        Ok(())
    }
}
