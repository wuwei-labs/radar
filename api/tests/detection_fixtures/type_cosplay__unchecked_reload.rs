// Real disclosure, minimised: Anchor's own `InterfaceAccount::reload` pinned
// owner stability and then re-deserialized *unchecked*, so an account could
// come back as a different type after a CPI. Fixed upstream by switching to the
// checked call.
//
// The rule missed it for a structural reason worth keeping a fixture for:
// `try_deserialize_unchecked` is a distinct identifier from `try_deserialize`,
// so it matched neither the trigger nor the exemption, and the function never
// entered the rule at all.
//
// The paired noise fixture is `type_cosplay__unchecked_constructor.rs`: the
// same unchecked call in a constructor is Anchor's deliberate
// `try_from_unchecked` and appears unchanged in the patched source, so
// reporting it would fire on fixed and vulnerable code alike.
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

pub struct Wrapper<T> {
    account: T,
    owner: Pubkey,
}

impl<T: AccountSerialize + AccountDeserialize + Clone> Wrapper<T> {
    /// Reloads the account from storage, e.g. to observe the effects of a CPI.
    pub fn reload(&mut self, info: &AccountInfo) -> Result<()> {
        // Owner stability is enforced...
        if info.owner != &self.owner {
            return Err(ProgramError::IllegalOwner.into());
        }

        // VULN: ...but the discriminator is not. The bytes are re-read into T
        // without proving they still describe a T.
        let mut data: &[u8] = &info.try_borrow_data()?;
        let new_val = T::try_deserialize_unchecked(&mut data)?;
        self.account = new_val;
        self.set_inner(self.account.clone());
        Ok(())
    }

    fn set_inner(&mut self, value: T) {
        self.account = value;
    }
}
