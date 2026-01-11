package com.example.demo.controller;

import com.example.demo.entity.Passenger;
import com.example.demo.entity.TicketOrder;
import com.example.demo.entity.Trip;
import com.example.demo.repositories.PassengerRepository;
import com.example.demo.repositories.TicketOrderRepository;
import com.example.demo.repositories.TripRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/ticket")
@CrossOrigin(origins = "*")
public class TicketController {

    @Autowired
    private PassengerRepository passengerRepo;

    @Autowired
    private TripRepository tripRepo;

    @Autowired
    private TicketOrderRepository orderRepo;

    @PostMapping("/order")
    public ResponseEntity<?> createOrder(@RequestBody Map<String, Object> request) {
        String phone = (String) request.get("contact_phone");
        String departureStation = (String) request.get("departure_station");
        String arrivalStation = (String) request.get("arrival_station");
        String dateStr = (String) request.get("departure_date");
        String carriageType = (String) request.get("carriage_type");
        Integer passengersCount = (Integer) request.get("number_of_passengers");

        if (passengersCount == null) {
            return ResponseEntity.badRequest().body(Map.of("status", "error", "message", "Количество пассажиров обязательно"));
        }

        LocalDate departureDate = LocalDate.parse(dateStr);

        Passenger passenger = passengerRepo.findByPhone(phone).orElse(null);
        if (passenger == null) {
            return ResponseEntity.badRequest().body(Map.of("status", "error", "message", "Пассажир не найден"));
        }

        List<Trip> trips = tripRepo.findByDepartureStationAndArrivalStationAndDepartureDate(
                departureStation, arrivalStation, departureDate);

        Trip selectedTrip = null;
        for (Trip trip : trips) {
            if (trip.getCarriageType().equalsIgnoreCase(carriageType) && trip.getAvailableSeats() >= passengersCount) {
                selectedTrip = trip;
                break;
            }
        }

        if (selectedTrip != null) {
            TicketOrder order = new TicketOrder();
            order.setDepartureStation(departureStation);
            order.setArrivalStation(arrivalStation);
            order.setDepartureDate(dateStr);
            order.setDepartureTime(selectedTrip.getDepartureTime());
            order.setTrainNumber(selectedTrip.getTrainNumber());
            order.setCarriageType(carriageType);
            order.setNumberOfPassengers(passengersCount);

            //сохранение passengers (если нет - сохраняем пустой массив)
            Object passengersObj = request.get("passengers");
            order.setPassengersJson(passengersObj != null ? passengersObj.toString() : "[]");
            order.setContactPhone(phone);
            order.setPassengersJson(String.valueOf(request.getOrDefault("passengers", "[]")));
            order.setContactPhone(phone);
            order.setPassengerName(passenger.getFullName());
            order.setPassport(passenger.getPassportSeries() + " " + passenger.getPassportNumber());

            orderRepo.save(order);

            selectedTrip.setAvailableSeats(selectedTrip.getAvailableSeats() - passengersCount);
            tripRepo.save(selectedTrip);

            Map<String, Object> response = new HashMap<>();
            response.put("status", "success");
            response.put("message", "Заказ оформлен!");
            response.put("train_number", selectedTrip.getTrainNumber());
            response.put("departure_date", dateStr);
            response.put("departure_time", selectedTrip.getDepartureTime());
            response.put("price_total", selectedTrip.getPrice() * passengersCount);
            response.put("passenger_name", passenger.getFullName());
            return ResponseEntity.ok(response);
        }

        // Если нет мест — ищем ближайшие
        LocalDate from = departureDate.minusDays(7);
        LocalDate to = departureDate.plusDays(7);
        List<Trip> nearbyTrips = tripRepo.findByDepartureStationAndArrivalStationAndDepartureDateBetween(
                departureStation, arrivalStation, from, to);

        List<Map<String, Object>> alternatives = new ArrayList<>();
        for (Trip trip : nearbyTrips) {
            if (trip.getAvailableSeats() >= passengersCount) {
                Map<String, Object> alt = new HashMap<>();
                alt.put("date", trip.getDepartureDate().toString());
                alt.put("time", trip.getDepartureTime());
                alt.put("train_number", trip.getTrainNumber());
                alt.put("carriage_type", trip.getCarriageType());
                alt.put("available_seats", trip.getAvailableSeats());
                alt.put("price", trip.getPrice());
                alternatives.add(alt);
            }
        }

        Map<String, Object> response = new HashMap<>();
        response.put("status", "no_seats");
        response.put("message", "На указанную дату мест нет. Предлагаю ближайшие варианты.");
        response.put("alternatives", alternatives);
        return ResponseEntity.ok(response);
    }
}