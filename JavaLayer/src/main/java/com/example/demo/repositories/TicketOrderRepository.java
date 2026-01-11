package com.example.demo.repositories;

import com.example.demo.entity.TicketOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface TicketOrderRepository extends JpaRepository<TicketOrder, Long> {
     List<TicketOrder> findByContactPhone(String phone);
}