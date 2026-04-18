const { faker } = require('@faker-js/faker');

function generateRandomUser(id = null) {
  const gender = faker.helpers.arrayElement(['male', 'female']);

  const address = {
    id: id ? id : faker.number.int({ min: 1, max: 10000 }),
    street: faker.location.streetAddress(),
    streetName: faker.location.street(),
    buildingNumber: faker.location.buildingNumber(),
    city: faker.location.city(),
    zipcode: faker.location.zipCode(),
    country: faker.location.country(),
    country_code: faker.location.countryCode('alpha-2'),
    latitude: parseFloat(faker.location.latitude()),
    longitude: parseFloat(faker.location.longitude())
  };

  return {
    id: id ? id : faker.number.int({ min: 1, max: 10000 }),
    firstname: faker.person.firstName(gender),
    lastname: faker.person.lastName(),
    email: faker.internet.email().toLowerCase(),
    phone: faker.phone.number(),
    birthday: faker.date.birthdate({ min: 18, max: 80, mode: 'age' }).toISOString().split('T')[0],
    gender: gender,
    address: address,
    website: faker.internet.url(),
    image: `http://placeimg.com/640/480/people`
  };
}

module.exports = { generateRandomUser };
