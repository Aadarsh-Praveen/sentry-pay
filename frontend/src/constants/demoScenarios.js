// Pre-loaded demo scenarios for the Load Demo dropdown.
// One scenario per verdict type so judges can test all three in seconds.

export const DEMO_SCENARIOS = [
    {
      id:    'bec',
      label: 'Supplier Fraud (BEC)',
      badge: '🔴 BLOCK',
      emailText: `Hi Sarah,
  
  Hope you're well. Just a quick note — we've recently migrated our treasury operations to a new banking provider. Could you please update your records and ensure the upcoming invoice of $47,000 is sent to our new account?
  
  New account details:
    Bank:    Metro Bank UK
    Account: GB94METRO00000087654321
    Sort:    00-00-87
  
  Please treat this as urgent as the invoice is due this Friday. Let me know if you need anything else.
  
  Best regards,
  Mike Johnson
  Apex Scaffolding Ltd`,
      amount:        47000,
      recipientName: 'Apex Scaffolding Ltd',
      accountNumber: 'GB94METRO00000087654321',
      paymentType:   'Wire',
      userId:        'demo_user_001',
    },
  
    {
      id:    'borderline',
      label: 'Borderline Invoice',
      badge: '🟡 FRICTION',
      emailText: `Hi,
  
  Please find attached invoice #INV-2094 for consulting services provided in April — $9,500 net 30.
  
  Payment details:
    Payee:   BuildRight Advisory Services
    Account: US44FIRST00000112233445
  
  Please process at your earliest convenience. Let me know if you have any questions.
  
  Kind regards,
  Derek Walsh
  BuildRight Advisory Services`,
      amount:        9500,
      recipientName: 'BuildRight Advisory Services',
      accountNumber: 'US44FIRST00000112233445',
      paymentType:   'ACH',
      userId:        'demo_user_001',
    },
  
    {
      id:    'regular',
      label: 'Regular Monthly Invoice',
      badge: '🟢 ALLOW',
      emailText: `Hi Sarah,
  
  Please see attached Invoice #7042 for office supplies delivered 12th May — $847.50.
  
  Same bank account as always. No changes to payment details.
  
  Thanks for your continued business!
  
  Kind regards,
  Jenny Parker
  City Office Supplies`,
      amount:        847.50,
      recipientName: 'City Office Supplies',
      accountNumber: 'GB82WEST12345698765432',
      paymentType:   'ACH',
      userId:        'demo_user_001',
    },
  ]
  
  // Payment type dropdown options
  export const PAYMENT_TYPES = [
    'Wire Transfer',
    'ACH',
    'Real-Time Payment',
    'Zelle',
    'Check',
  ]